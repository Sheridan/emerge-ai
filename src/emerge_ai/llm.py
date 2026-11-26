"""Minimal OpenAI-compatible chat client (stdlib only) with native tool-calling."""

from __future__ import annotations

import json
import sys
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


class LLMError(RuntimeError):
    pass


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
    def __init__(self, cfg: Config, timeout: float = 240.0, *, show_reasoning: bool = False):
        self.cfg = cfg
        self.show_reasoning = show_reasoning
        try:
            self.base = require_endpoint(cfg).rstrip("/")
        except ConfigError as exc:
            raise LLMError(str(exc)) from exc
        self.timeout = timeout

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
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except Exception as exc:
            raise LLMError(f"emerge-ai: LLM request failed: {exc}") from exc
        return self._parse(data)

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
        """Show reasoning only when verbose mode (-v/--verbose) enabled it; content always.
        Colors come from cfg.llm_colors; non-TTY streams get plain text (spec: console-output)."""
        stream = sys.stderr if stream is None else stream
        palette = ui.resolve_palette(getattr(self.cfg, "llm_colors", None))
        if self.show_reasoning and resp.reasoning:
            print(
                ui.paint(stream, ui.color_sgr(palette["reasoning"]), f"[reasoning] {resp.reasoning}"),
                file=stream,
            )
        if resp.content:
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
