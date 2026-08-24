"""Three-state terminal mascot rendering for the Allright CLI."""

from __future__ import annotations

import base64
import os
import shutil
import sys
from pathlib import Path

MASCOT_NORMAL = "normal"
MASCOT_ERROR = "error"
MASCOT_OFFLINE = "offline"
MASCOT_STATES = (MASCOT_NORMAL, MASCOT_ERROR, MASCOT_OFFLINE)

_OFFLINE_ERROR_MARKERS = (
    "api key",
    "api_key",
    "authentication",
    "connection",
    "could not reach",
    "dns",
    "forbidden",
    "http 401",
    "http 403",
    "network",
    "no route to host",
    "remote disconnected",
    "timed out",
    "timeout",
    "unauthorized",
)


def mascot_asset_path(state: str, suffix: str = ".png") -> Path:
    """Return the packaged asset path for one mascot state."""
    if state not in MASCOT_STATES:
        raise ValueError(f"unknown mascot state: {state}")
    return Path(__file__).parent / "assets" / "mascots" / f"{state}{suffix}"


def _error_chain_text(error: BaseException | None) -> str:
    messages = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current))
        current = current.__cause__ or current.__context__
    return "\n".join(messages).lower()


def classify_mascot_state(model_client=None, error: BaseException | None = None) -> str:
    """Map provider configuration or a runtime failure to a mascot state."""
    if hasattr(model_client, "api_key") and not str(getattr(model_client, "api_key", "") or "").strip():
        return MASCOT_OFFLINE
    if error is None:
        return MASCOT_NORMAL
    error_text = _error_chain_text(error)
    if any(marker in error_text for marker in _OFFLINE_ERROR_MARKERS):
        return MASCOT_OFFLINE
    return MASCOT_ERROR


def _terminal_protocol(env) -> str:
    override = str(env.get("ALLRIGHT_MASCOT_PROTOCOL", "")).strip().lower()
    if override in {"off", "ansi", "kitty", "iterm"}:
        return override
    term = str(env.get("TERM", "")).lower()
    term_program = str(env.get("TERM_PROGRAM", "")).lower()
    if env.get("KITTY_WINDOW_ID") or "kitty" in term:
        return "kitty"
    if term_program in {"iterm.app", "wezterm"}:
        return "iterm"
    return "ansi"


def _render_kitty(png_data: bytes) -> str:
    encoded = base64.b64encode(png_data).decode("ascii")
    chunks = [encoded[index : index + 4096] for index in range(0, len(encoded), 4096)]
    rendered = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        if index == 0:
            rendered.append(f"\x1b_Ga=T,f=100,t=d,c=30,r=12,m={more};{chunk}\x1b\\")
        else:
            rendered.append(f"\x1b_Gm={more};{chunk}\x1b\\")
    return "".join(rendered)


def _render_iterm(png_data: bytes) -> str:
    encoded = base64.b64encode(png_data).decode("ascii")
    return f"\x1b]1337;File=inline=1;width=30;height=12;preserveAspectRatio=1:{encoded}\x07"


def _mascot_indent(env, width: int = 30) -> str:
    try:
        columns = int(env.get("COLUMNS", ""))
    except (TypeError, ValueError):
        columns = 0
    if columns <= 0:
        columns = shutil.get_terminal_size((80, 20)).columns
    return " " * max(0, (columns - width) // 2)


def render_mascot(state: str, stream=None, env=None) -> str:
    """Render a mascot using a native image protocol or packaged ANSI fallback."""
    if state not in MASCOT_STATES:
        raise ValueError(f"unknown mascot state: {state}")
    stream = stream or sys.stdout
    env = os.environ if env is None else env
    protocol = _terminal_protocol(env)
    if protocol == "off" or str(env.get("ALLRIGHT_MASCOT", "")).lower() in {"0", "false", "off"}:
        return ""
    force = str(env.get("ALLRIGHT_FORCE_MASCOT", "")).lower() in {"1", "true", "on"}
    if not force and not getattr(stream, "isatty", lambda: False)():
        return ""
    indent = _mascot_indent(env)
    if protocol == "kitty":
        return indent + _render_kitty(mascot_asset_path(state).read_bytes())
    if protocol == "iterm":
        return indent + _render_iterm(mascot_asset_path(state).read_bytes())
    if env.get("NO_COLOR") or str(env.get("TERM", "")).lower() == "dumb":
        return f"[allright mascot: {state}]"
    ansi = mascot_asset_path(state, ".ansi").read_text(encoding="utf-8").rstrip("\r\n")
    return "\n".join(indent + line for line in ansi.splitlines())


def print_mascot(state: str, stream=None, env=None) -> None:
    """Print a mascot only when the active terminal supports a useful rendering."""
    stream = stream or sys.stdout
    rendered = render_mascot(state, stream=stream, env=env)
    if rendered:
        print(rendered, file=stream)
