"""Terminal styling (spec: console-output): stdlib-only ANSI paint.

Coloring is decided per call, per stream: TTY + no NO_COLOR + TERM != dumb;
pipes, redirects and CI stay plain and no config overrides that. Emerge's own
passthrough output is never touched here — only aimerge's messages, plan
digests and LLM blocks are painted, from the fixed whitelist below.
"""

from __future__ import annotations

import json
import os
import re
import sys

CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")

SGR_RESET = "0"
STYLES = {"bold": "1", "dim": "2"}
FG_COLORS = {
    "black": "30", "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36", "white": "37",
    "bright-black": "90", "bright-red": "91", "bright-green": "92",
    "bright-yellow": "93", "bright-blue": "94", "bright-magenta": "95",
    "bright-cyan": "96", "bright-white": "97",
}
# The only names accepted by config (llm_colors) and the only SGR sources.
# "off" (like null in JSON) disables color for a palette slot.
COLOR_SGR: dict[str, str] = {"off": "", **STYLES, **FG_COLORS}

LLM_KEYS = ("content", "reasoning", "question")
DEFAULT_LLM_COLORS = {"content": "cyan", "reasoning": "dim", "question": "yellow"}
QUESTION_PREFIX = "QUESTION:"

# Risk-tier gradient for plan digest / doctor lines (design D2).
TIER_GRADIENT = {1: "red", 2: "yellow", 3: "green", 4: "cyan", 5: "dim"}

# Finding-kind importance scale (spec: console-output, kind colors): red means
# merge-blocking criticals, yellow an actionable condition, cyan informational;
# unknown kinds paint plain. Fixed palette — llm_colors does not reach it.
KIND_COLORS = {
    "severity": "red",
    "dep-conflict": "red",
    "conflict": "red",
    "empty-update": "red",
    "masked": "yellow",
    "dep-required": "yellow",
    "config-updating": "yellow",
    "world-file": "yellow",
    "important": "cyan",
    "warning": "cyan",
}

PREFIX = "aimerge: "
PROMPT_SGR = "1;33"  # bold + yellow: consent prompts stand out (design D2)

# Decision-block chrome (spec: console-output, decision highlighting): fixed
# colors, never llm_colors; the banner separates a menu from prose even where
# color is off (design D2).
DECISION_BODY = "yellow"
DECISION_NUM = "green"
DECISION_BANNER = ("── decisions " + "─" * 40)[:40]


def supports_color(stream) -> bool:
    """TTY + NO_COLOR unset + TERM != dumb, evaluated per call (not cached at
    import), so tests can swap isatty and env around the same process."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def color_sgr(name) -> str:
    """SGR parameter for a whitelisted color name; unknown names paint plain."""
    if name is None:
        return ""
    return COLOR_SGR.get(name, "")


def kind_sgr(kind) -> str:
    """SGR for a finding-kind token from KIND_COLORS; unknown names and
    non-strings paint plain, like color_sgr."""
    name = KIND_COLORS.get(kind) if isinstance(kind, str) else None
    return color_sgr(name)


def paint(stream, sgr: str, text: str) -> str:
    """Wrap text in an SGR sequence unless the stream gets no color."""
    if not sgr or not text or not supports_color(stream):
        return text
    return f"\x1b[{sgr}m{text}\x1b[{SGR_RESET}m"


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences (design D5: input hygiene for the LLM)."""
    return CSI_RE.sub("", text)


def err(text: str, stream=None) -> str:
    return paint(sys.stderr if stream is None else stream, color_sgr("red"), PREFIX + text)


def warn(text: str, stream=None) -> str:
    return paint(sys.stderr if stream is None else stream, color_sgr("yellow"), PREFIX + text)


def ok(text: str, stream=None) -> str:
    return paint(sys.stderr if stream is None else stream, color_sgr("green"), PREFIX + text)


def info(text: str, stream=None) -> str:
    return PREFIX + text


def activity(text: str, stream=None) -> str:
    """Progress-logging line: announces what aimerge is about to do next
    (spec: progress-logging). Info-style — deliberately unpainted even on a
    TTY, so pipes, NO_COLOR and TERM=dumb render the exact same plain text.
    Callers print it to stderr; emerge's stdout passthrough stays untouched."""
    return PREFIX + text


def clip(text: str, limit: int = 200) -> str:
    """Cap a value to `limit` characters with an explicit truncation marker,
    so one activity line never becomes a screen-filling dump."""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f" …[capped, {len(text)} chars total]"


# --- human-readable request dump (spec: progress-logging, design D1-D5) -----

# Two caps replace the old single-line 8000-char JSON cap: one per rendered
# text field, one for the whole block, each truncation marked explicitly.
DUMP_FIELD_LIMIT = 400
DUMP_TOTAL_LIMIT = 4000


def _dump_num(n: int) -> str:
    """Group digits with a thin separator so sizes stay readable."""
    return f"{n:,}".replace(",", " ")


def _dump_oneline(text: str) -> str:
    """Collapse real newlines into ⏎ so one logical element is one line."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "⏎")


def _dump_maybe_json(text: str):
    """Parse JSON-looking strings (tool results arrive as text) for the
    k=v rendering; anything else stays plain text (design D4)."""
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            return json.loads(stripped)
        except ValueError:
            return None
    return None


def _dump_atom(value, field_limit: int) -> str:
    """Scalar rendering: as-is, single-line, capped via clip with the size of
    the ORIGINAL value; ambiguous strings (spaces, empty) get quoted."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        flat = _dump_oneline(value)
        quoted = flat == "" or any(c.isspace() for c in flat)
        text = clip(flat, field_limit)
        return f'"{text}"' if quoted else text
    return str(value)


def _dump_flat(value, field_limit: int) -> str:
    """One-line value rendering — dicts as `k=v`, lists as indexed elements.
    JSON syntax (braces, escaped quotes) never appears (spec scenario)."""
    if isinstance(value, dict):
        return ", ".join(f"{k}={_dump_flat(v, field_limit)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(
            f"[{i}]={_dump_flat(v, field_limit)}" for i, v in enumerate(value, 1)
        )
    return _dump_atom(value, field_limit)


def _dump_struct(key: str, value, field_limit: int, sep: str = ", ") -> list[str]:
    """Type-driven rendering (design D4): first line carries `key`; composites
    nested deeper than one level continue on indented lines."""
    if not isinstance(value, (dict, list)):
        atom = _dump_atom(value, field_limit)
        return [f"{key}={atom}" if key else atom]
    items = value.items() if isinstance(value, dict) else enumerate(value, 1)
    head, tail = [], []
    for k, v in items:
        label = str(k) if isinstance(value, dict) else f"[{k}]"
        if isinstance(v, (dict, list)) and v:
            head.append(f"{label}:")
            tail.extend("  " + line for line in _dump_struct(label, v, field_limit, sep))
        else:
            head.append(_dump_struct(label, v, field_limit, sep)[0])
    first = sep.join(head) or "(empty)"
    return ([f"{key}: {first}"] if key else [first]) + tail


def _dump_message(index: int, msg, field_limit: int) -> list[str]:
    """One block per message (spec «Сообщения по блоку»): № · role · size ·
    preview; tool-calls as name(args), tool results as k=v pairs."""
    if not isinstance(msg, dict):
        return [f"  [{index}] {_dump_atom(msg, field_limit)}"]
    ident = f"[{index}] {msg.get('role', '?')}"
    if msg.get("tool_call_id"):
        ident += f" {msg['tool_call_id']}"
    head = f"  {ident}"
    content = msg.get("content")
    if isinstance(content, str) and content:
        parsed = _dump_maybe_json(content)
        if isinstance(parsed, (dict, list)):
            preview = _dump_struct("", parsed, field_limit, sep=" · ")
        else:
            preview = [clip(_dump_oneline(content), field_limit)]
        head += f" · {_dump_num(len(content))} chars: {preview[0]}"
        extra = ["    " + line for line in preview[1:]]
    elif isinstance(content, list) and content:
        text_len = sum(len(str(p.get("text", ""))) for p in content if isinstance(p, dict))
        parts = [_dump_flat(p, field_limit) for p in content]
        head += f" · {_dump_num(text_len)} chars: {' · '.join(parts)}"
        extra = []
    else:
        extra = []
    calls = msg.get("tool_calls") or []
    if calls:
        rendered = []
        for call in calls:
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = _dump_maybe_json(args)
                if args is None:
                    args = fn.get("arguments", "")
            rendered.append(f"{fn.get('name', '?')}({_dump_flat(args, field_limit)})")
        head += f" · tool_calls: {', '.join(rendered)}"
    return [head, *extra]


def render_request(payload: dict, api_key: str | None = None,
                   field_limit: int = DUMP_FIELD_LIMIT,
                   total_limit: int = DUMP_TOTAL_LIMIT) -> list[str]:
    """Human-readable request dump (spec: progress-logging, design D2-D5):
    one line per logical payload element, no JSON syntax, fields capped with
    an explicit marker, the whole block capped with a summary line, the API
    key masked. Headers are never part of the dump."""
    messages = payload.get("messages") or []
    tools = payload.get("tools") or []
    body_chars = len(json.dumps(payload, ensure_ascii=False))
    lines = [
        f"request: model={payload.get('model', '?')} "
        f"temperature={payload.get('temperature')} "
        f"messages={_dump_num(len(messages))} tools={_dump_num(len(tools))} "
        f"body={_dump_num(body_chars)} chars"
    ]
    known = {"model", "temperature", "messages", "tools"}
    for key, value in payload.items():
        if key in known:
            continue
        lines += ["  " + line for line in _dump_struct(key, value, field_limit)]
    for index, msg in enumerate(messages, start=1):
        lines += _dump_message(index, msg, field_limit)
    for index, tool in enumerate(tools, start=1):
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        name = fn.get("name", "?")
        desc = _dump_oneline(str(fn.get("description", "")))
        params = (fn.get("parameters") or {}).get("properties") or {}
        line = f"  tool[{index}/{len(tools)}] {name} — {clip(desc, field_limit)}"
        if params:
            line += f" (args: {', '.join(params)})"
        lines.append(line)
    total = 0
    shown: list[str] = []
    for line in lines:
        if shown and total + len(line) > total_limit:
            shown.append(
                f"dump truncated: shown {len(shown)} of {len(lines)} lines")
            break
        shown.append(line)
        total += len(line)
    if api_key:
        shown = [line.replace(api_key, "***") for line in shown]
    return shown


def prompt(text: str, stream=None) -> str:
    return paint(sys.stdout if stream is None else stream, PROMPT_SGR, text)


# --- decision-choice block chrome (spec: console-output, decision highlight) --

def decision_banner_line(stream) -> str:
    """Fence line opening a decision block: bold yellow on a color stream, the
    very same plain text where color is off. Printed with a blank line before
    it and followed by a blank line after the block (design D2)."""
    return paint(stream, PROMPT_SGR, DECISION_BANNER)


def decision_choice(stream, num_token: str, text: str) -> str:
    """One numbered choice line: the number token green, the block body
    yellow. Plain streams get the concatenated text untouched."""
    return (paint(stream, color_sgr(DECISION_NUM), num_token)
            + paint(stream, color_sgr(DECISION_BODY), text))


def decision_text(stream, text: str) -> str:
    """A non-numbered line inside a decision block (details, [c]/[q] hints):
    the block's yellow body."""
    return paint(stream, color_sgr(DECISION_BODY), text)


def resolve_palette(llm_colors, warn=None) -> dict:
    """Validate the llm_colors mapping (design D4): whitelist names only, raw
    escape strings never reach the terminal; invalid/missing -> default."""
    if warn is None:
        def warn(msg: str) -> None:
            pass
    if llm_colors is not None and not isinstance(llm_colors, dict):
        warn("aimerge: config: llm_colors must be a JSON object; using defaults")
        llm_colors = {}
    given = llm_colors or {}
    palette: dict = {}
    for key in LLM_KEYS:
        default = DEFAULT_LLM_COLORS[key]
        name = given.get(key, default)
        if name is None or name in COLOR_SGR:
            palette[key] = name
            continue
        warn(
            f"aimerge: config: llm_colors.{key}: unknown color {name!r}; "
            f"using default {default!r}"
        )
        palette[key] = default
    return palette


def paint_llm_block(text: str, palette, stream) -> None:
    """Uniform renderer for every user-visible LLM block (design D3): lines
    starting with the QUESTION: marker get the question color, the rest the
    content color; palette names outside the whitelist paint plain."""
    pal = resolve_palette(palette)
    for line in text.splitlines():
        key = "question" if line.startswith(QUESTION_PREFIX) else "content"
        print(paint(stream, color_sgr(pal[key]), line), file=stream)


# --- interactive operator question channel (spec: agent-loop-consent, design D6) ---

CHOICE_HINT = "[{choices}] choose, [c] own text, [q] quit: "


def render_question(question: str, options, palette, stream) -> None:
    """Print one operator question with numbered options (design D6): the
    question line takes the palette's question color, the options form the
    highlighted decision block (spec: console-output) — a blank line, the
    banner, yellow option lines with green numbers, a closing blank line.
    Without options no choice block is shown. Coloring is per stream, so a
    pipe, NO_COLOR or TERM=dumb renders the very same text plain; the blank
    lines and the banner stay either way."""
    pal = resolve_palette(palette)
    print(paint(stream, color_sgr(pal["question"]), question), file=stream)
    if not options:
        return
    print(file=stream)
    print(decision_banner_line(stream), file=stream)
    for num, option in enumerate(options, start=1):
        label = str(option.get("label", "")).strip()
        consequences = str(option.get("consequences", "")).strip()
        body = f" {label}"
        if consequences:
            body += f" — {consequences}"
        print(decision_choice(stream, f"  {num}.", body), file=stream)
    print(file=stream)


def choice_prompt(count: int, stream=None) -> str:
    """Input line for a question with `count` options, in the consent-prompt
    style (bold yellow) so it stands out from the agent's own text."""
    choices = f"1..{count}" if count > 1 else "1"
    return prompt(CHOICE_HINT.format(choices=choices), stream=stream)


def echo_answer(text: str, palette, stream) -> None:
    """Echo the accepted answer right after the input, so the transcript of an
    incident reads back without the operator having to scroll."""
    pal = resolve_palette(palette)
    print(paint(stream, color_sgr(pal["content"]), f"> {text}"), file=stream)
