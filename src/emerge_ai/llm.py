"""Minimal OpenAI-compatible chat client (stdlib only) with native tool-calling."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field

from emerge_ai import ui
from emerge_ai.config import Config, ConfigError, require_endpoint


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Response:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    # True when the answer was already shown live while streaming (design D6):
    # additive, the default keeps every existing constructor and caller as-is.
    displayed: bool = False


class LLMError(RuntimeError):
    pass


class _StreamUnavailable(RuntimeError):
    """The endpoint gave no stream before anything was printed — the same
    payload is retried once without the streaming flag (design D7)."""


class _LiveWriter:
    """Streaming presentation (design D5): reasoning deltas print the moment
    they arrive, content is buffered to whole lines so the QUESTION: rule
    colors each line as a unit. ui.paint decides coloring per stream, so
    pipes, NO_COLOR and TERM=dumb get the very same texts plain."""

    def __init__(self, stream, palette):
        self.out = stream
        self.reasoning_sgr = ui.color_sgr(palette["reasoning"])
        self.content_sgr = ui.color_sgr(palette["content"])
        self.question_sgr = ui.color_sgr(palette["question"])
        self.emitted = False
        self._block = ""
        self._pending = ""

    def delta(self, kind: str, text: str) -> None:
        """Callback seam used by the accumulator (design D4): show each delta
        the moment it is folded in."""
        (self.reasoning if kind == "reasoning" else self.content)(text)

    def reasoning(self, delta: str) -> None:
        if not delta:
            return
        if self._block == "content":
            self._flush_pending()
        if self._block != "reasoning":
            # same marker the single-request path prints, so even a plain pipe
            # tells reasoning from answer (README: `[reasoning] ...` per call)
            print(ui.paint(self.out, self.reasoning_sgr, "[reasoning] "),
                  end="", flush=True, file=self.out)
        print(ui.paint(self.out, self.reasoning_sgr, delta), end="",
              flush=True, file=self.out)
        self.emitted = True
        self._block = "reasoning"

    def content(self, delta: str) -> None:
        if not delta:
            return
        if self._block == "reasoning":
            print(file=self.out, flush=True)  # end the reasoning line
        self._block = "content"
        self.emitted = True
        self._pending += delta
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._content_line(line)

    def _content_line(self, line: str) -> None:
        sgr = self.question_sgr if line.startswith(ui.QUESTION_PREFIX) else self.content_sgr
        print(ui.paint(self.out, sgr, line), file=self.out, flush=True)

    def _flush_pending(self) -> None:
        if self._pending:
            self._content_line(self._pending)
            self._pending = ""

    def finalize(self) -> None:
        """Terminate the unfinished streamed line before any activity line
        follows (spec: строка активности с новой строки)."""
        if self._block == "content":
            self._flush_pending()
        elif self._block == "reasoning":
            print(file=self.out, flush=True)
        self._block = ""


def _iter_sse(resp, stats: dict):
    """Iterate parsed chunks of an SSE response (design D3): utf-8 with
    replacement (same tolerant decoding as emerge's output), blank line ends
    an event, ':' lines are keep-alive comments, unknown fields ignored,
    `data: [DONE]` terminates; an unparseable data chunk is skipped with a
    counter instead of killing the run. stats receives bad/done counters."""
    data: list[str] = []
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if not data:
                continue
            body = "\n".join(data)
            data = []
            if body == "[DONE]":
                stats["done"] = True
                return
            try:
                obj = json.loads(body)
            except ValueError:
                stats["bad"] += 1
                continue
            stats["chunks"] = stats.get("chunks", 0) + 1
            yield obj
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        # any other SSE field is ignored (design D3)


def _accumulate(chunks, on_delta=None):
    """Fold a chunk stream into a Response (design D4): content/reasoning are
    concatenated deltas, tool-calls live in a table keyed by `index` (first
    non-empty id/name, arguments concatenated, same {"_raw": ...} fallback as
    _parse), finish_reason is the last non-empty one. Returns (Response,
    usage); usage only feeds the duration line. The result equals what _parse
    yields for the same whole reply."""
    content: list[str] = []
    reasoning: list[str] = []
    calls: dict[int, dict] = {}
    finish = ""
    usage: dict = {}
    for chunk in chunks:
        if chunk.get("usage"):
            usage.update(chunk["usage"])
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
                if on_delta:
                    on_delta("reasoning", delta["reasoning_content"])
            if delta.get("content"):
                content.append(delta["content"])
                if on_delta:
                    on_delta("content", delta["content"])
            for call in delta.get("tool_calls") or []:
                slot = calls.setdefault(
                    call.get("index", len(calls)),
                    {"id": "", "name": "", "arguments": ""})
                if call.get("id"):
                    slot["id"] = call["id"]
                fn = call.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                slot["arguments"] += fn.get("arguments") or ""
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    tool_calls = []
    for index in sorted(calls):
        raw = calls[index]["arguments"]
        try:
            args = json.loads(raw or "{}")
        except json.JSONDecodeError:
            args = {"_raw": raw}
        tool_calls.append(ToolCall(id=calls[index]["id"], name=calls[index]["name"],
                                   arguments=args))
    return (Response(content="".join(content), reasoning="".join(reasoning),
                     tool_calls=tool_calls, finish_reason=finish), usage)


class LimitExhausted(LLMError):
    """Distinguishable 'a limit was hit' signal (spec: Исчерпание лимита токенов):
    reason is "tokens" (endpoint truncated the answer) or "rounds" (tool-loop
    budget). Carries the partial answer and the message history so the operator
    can resume the analysis from where it stopped."""

    def __init__(self, reason: str, partial: "Response | None" = None,
                 messages: list | None = None):
        detail = ("endpoint truncated the answer at the token/context limit"
                  if reason == "tokens" else "tool-round budget exhausted")
        super().__init__(f"emerge-ai: limit exhausted ({reason}): {detail}")
        self.reason = reason
        self.partial = partial
        self.messages = messages or []


def try_structured(reply: str) -> dict | None:
    """Extract the first JSON object from a model reply and parse it (the
    shared schema-parsing seam for structured prompts, spec: run-reporting):
    no object or invalid JSON -> None, never an exception."""
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class LLMClient:
    def __init__(self, cfg: Config, timeout: float = 240.0, *, verbose: bool = False,
                 stream=None):
        self.cfg = cfg
        # -v/--verbose: payload dumps now, reasoning output too (change
        # fix-verbose-thinking-output) — one knob for "show me the details".
        self.verbose = verbose
        # announcement seam: stderr by default, tests inject a buffer
        self.stream = stream
        try:
            self.base = require_endpoint(cfg).rstrip("/")
        except ConfigError as exc:
            raise LLMError(str(exc)) from exc
        self.timeout = timeout
        # an endpoint that refused the stream is remembered per client, so a
        # ten-call agent loop does not pay the fallback retry every round
        # (design D7)
        self._stream_supported = True

    def _announce(self, msg: str) -> None:
        """One progress-logging line on stderr (spec: progress-logging)."""
        print(ui.activity(msg), file=self.stream or sys.stderr)

    def _request_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        return headers

    def _dump_request_lines(self, payload: dict) -> list[str]:
        """Verbose request dump (spec: progress-logging): human-readable
        lines — the JSON payload only, headers are never dumped; an api_key
        value that leaked into message text is masked; fields and the whole
        block are capped with explicit markers (ui.render_request)."""
        return ui.render_request(payload, api_key=self.cfg.api_key)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
    ) -> Response:
        payload: dict = {
            "model": self.cfg.model or "default",
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        self._announce(
            f"sending request to LLM (model={payload['model']}, "
            f"{len(messages)} messages, tools={len(tools or [])})"
        )
        if self.verbose:
            # one activity line per payload element, before the answer line
            # (design D6: the dump's place in the sequence is unchanged)
            for line in self._dump_request_lines(payload):
                self._announce(line)
        # -v is the only streaming switch (design D2): streaming where nothing
        # would be shown would add network risk for no benefit
        if self.verbose and self._stream_supported:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        started = time.monotonic()
        if payload.get("stream"):
            usage: dict = {}
            try:
                parsed, _emitted = self._stream_request(payload, usage)
            except _StreamUnavailable as exc:
                # one quiet retry without the stream flag (design D7); the
                # refusal is remembered so later calls skip the attempt
                payload.pop("stream")
                payload.pop("stream_options")
                self._stream_supported = False
                self._announce(f"{exc}; single request instead")
            else:
                answer = (
                    f"LLM answered in {time.monotonic() - started:.1f}s"
                    f" (finish={parsed.finish_reason or 'unknown'})"
                )
                if usage:
                    answer += (
                        f" [tokens {usage.get('prompt_tokens', '?')}"
                        f"+{usage.get('completion_tokens', '?')}]"
                    )
                self._announce(answer)
                return parsed
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body,
            headers=self._request_headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except Exception as exc:
            raise LLMError(f"emerge-ai: LLM request failed: {exc}") from exc
        parsed = self._parse(data)
        self._announce(
            f"LLM answered in {time.monotonic() - started:.1f}s"
            f" (finish={parsed.finish_reason or 'unknown'})"
        )
        if self.verbose and parsed.reasoning:
            # The single reasoning print site (spec: config-prompts, change
            # fix-verbose-thinking-output): every model call shows thinking
            # under -v — direct chats included, not just the tool loop.
            out = self.stream or sys.stderr
            palette = ui.resolve_palette(getattr(self.cfg, "llm_colors", None))
            print(
                ui.paint(out, ui.color_sgr(palette["reasoning"]),
                         f"[reasoning] {parsed.reasoning}"),
                file=out,
            )
        return parsed

    def _stream_request(self, payload: dict, usage_out: dict | None = None):
        """Streaming request (design D1/D7): returns (Response, emitted).

        Raises _StreamUnavailable when the reply is not an event stream, when
        it carries no usable chunks, or when it breaks before anything was
        printed — the caller then retries once without the stream flag. A
        stream that already showed text and then broke is a plain LLMError:
        a retry would duplicate the on-screen text."""
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body,
            headers=self._request_headers(), method="POST"
        )
        out = self.stream or sys.stderr
        palette = ui.resolve_palette(getattr(self.cfg, "llm_colors", None))
        writer = _LiveWriter(out, palette)
        stats = {"bad": 0, "done": False, "chunks": 0}
        try:
            resp_cm = urllib.request.urlopen(req, timeout=self.timeout)
        except Exception as exc:
            raise _StreamUnavailable(f"stream request failed: {exc}") from exc
        try:
            with resp_cm as resp:
                headers = getattr(resp, "headers", None)
                ctype = headers.get("Content-Type", "") if headers is not None else ""
                if "text/event-stream" not in str(ctype).lower():
                    raise _StreamUnavailable(
                        f"endpoint replied without an event stream ({ctype or 'no content type'})")
                try:
                    parsed, usage = _accumulate(
                        _iter_sse(resp, stats), on_delta=writer.delta)
                except Exception as exc:
                    if writer.emitted:
                        raise LLMError(f"emerge-ai: LLM request failed: {exc}") from exc
                    raise _StreamUnavailable(f"stream broke before output: {exc}") from exc
        except Exception:
            writer.finalize()  # never leave a half line before the fallback
            raise
        writer.finalize()
        if not stats["chunks"] and (stats["bad"] or not stats["done"]):
            raise _StreamUnavailable("endpoint stream carried no chunks")
        if not stats["done"]:
            # ended without [DONE]: an interrupted stream that already showed
            # text is an endpoint failure, never a silent retry (spec)
            if writer.emitted:
                raise LLMError("emerge-ai: LLM request failed: stream ended before [DONE]")
            raise _StreamUnavailable("stream ended before [DONE]")
        if usage_out is not None:
            usage_out.update(usage)
        parsed.displayed = writer.emitted
        return parsed, writer.emitted

    @staticmethod
    def _parse(data: dict) -> Response:
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"emerge-ai: unexpected LLM reply: {data}") from exc
        msg = choice.get("message", {})
        calls = []
        for call in msg.get("tool_calls") or []:
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments", "")}
            calls.append(ToolCall(id=call.get("id", ""), name=fn["name"], arguments=args))
        return Response(
            content=msg.get("content") or "",
            reasoning=msg.get("reasoning_content") or "",
            tool_calls=calls,
            finish_reason=choice.get("finish_reason") or "",
        )

    def render(self, resp: Response, stream=None) -> None:
        """Content only: reasoning printing lives in chat() now (change
        fix-verbose-thinking-output), so the tool loop never shows it twice.
        A response already shown live while streaming is not reprinted
        (design D6). Colors come from cfg.llm_colors; non-TTY streams get
        plain text (spec: console-output)."""
        stream = sys.stderr if stream is None else stream
        palette = ui.resolve_palette(getattr(self.cfg, "llm_colors", None))
        if resp.content and not resp.displayed:
            ui.paint_llm_block(resp.content, palette, stream)


def run_tool_loop(
    client: LLMClient,
    messages: list[dict],
    tools: list[dict],
    dispatch,
    max_rounds: int = 8,
    render_to=None,
) -> Response:
    """Drive model->tool->model until a content answer or the round budget."""
    msgs = list(messages)
    last: Response | None = None
    for _ in range(max_rounds):
        last = client.chat(msgs, tools=tools)
        if render_to is not None:
            client.render(last, stream=render_to)
        if last.finish_reason == "length":
            # truncated generation — never treat it as a final answer (task 1.2)
            raise LimitExhausted("tokens", partial=last, messages=msgs)
        if not last.tool_calls:
            return last
        msgs.append(
            {
                "role": "assistant",
                "content": last.content or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in last.tool_calls
                ],
            }
        )
        for call in last.tool_calls:
            result = dispatch(call.name, call.arguments)
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    raise LimitExhausted("rounds", partial=last, messages=msgs)
