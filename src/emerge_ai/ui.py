"""Terminal styling (spec: console-output): stdlib-only ANSI paint.

Coloring is decided per call, per stream: TTY + no NO_COLOR + TERM != dumb;
pipes, redirects and CI stay plain and no config overrides that. Emerge's own
passthrough output is never touched here — only emerge-ai's messages, plan
digests and LLM blocks are painted, from the fixed whitelist below.
"""

from __future__ import annotations

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

PREFIX = "emerge-ai: "
PROMPT_SGR = "1;33"  # bold + yellow: consent prompts stand out (design D2)


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
    """Progress-logging line: announces what emerge-ai is about to do next
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


def prompt(text: str, stream=None) -> str:
    return paint(sys.stdout if stream is None else stream, PROMPT_SGR, text)


def resolve_palette(llm_colors, warn=None) -> dict:
    """Validate the llm_colors mapping (design D4): whitelist names only, raw
    escape strings never reach the terminal; invalid/missing -> default."""
    if warn is None:
        def warn(msg: str) -> None:
            pass
    if llm_colors is not None and not isinstance(llm_colors, dict):
        warn("emerge-ai: config: llm_colors must be a JSON object; using defaults")
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
            f"emerge-ai: config: llm_colors.{key}: unknown color {name!r}; "
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
    question line takes the palette's question color, the options and their
    consequences the content color. Coloring is per stream, so a pipe,
    NO_COLOR or TERM=dumb renders the very same text plain."""
    pal = resolve_palette(palette)
    print(paint(stream, color_sgr(pal["question"]), question), file=stream)
    for num, option in enumerate(options or (), start=1):
        label = str(option.get("label", "")).strip()
        consequences = str(option.get("consequences", "")).strip()
        line = f"  {num}. {label}"
        if consequences:
            line += f" — {consequences}"
        print(paint(stream, color_sgr(pal["content"]), line), file=stream)


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
