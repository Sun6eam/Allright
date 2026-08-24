"""Three-state ASCII cat mascot rendering for the Allright CLI."""

from __future__ import annotations

import os
import sys

MASCOT_NORMAL = "normal"
MASCOT_ERROR = "error"
MASCOT_OFFLINE = "offline"
MASCOT_STATES = (MASCOT_NORMAL, MASCOT_ERROR, MASCOT_OFFLINE)

MASCOT_ART = {
    MASCOT_NORMAL: (
        "    /\\_/\\",
        "   ( ^.^ )",
        "   / > < \\",
        "  /|  A  |\\",
        " (_|_____|_)",
    ),
    MASCOT_OFFLINE: (
        " z  /\\_/\\",
        "   ( -.- )",
        "   /  ~  \\",
        "  /|  A  |\\",
        " (_|_____|_) x",
    ),
    MASCOT_ERROR: (
        " !  /\\_/\\",
        "   ( x.x )",
        "   /  !  \\",
        "  /|  A  |\\",
        " (_|_____|_)",
    ),
}

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


def mascot_art(state: str) -> str:
    """Return the fixed-width ASCII cat for a mascot state."""
    if state not in MASCOT_STATES:
        raise ValueError(f"unknown mascot state: {state}")
    return "\n".join(MASCOT_ART[state])


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


def render_mascot(state: str, stream=None, env=None) -> str:
    """Render a portable ASCII mascot without terminal image protocols."""
    if state not in MASCOT_STATES:
        raise ValueError(f"unknown mascot state: {state}")
    stream = stream or sys.stdout
    env = os.environ if env is None else env
    disabled = str(env.get("ALLRIGHT_MASCOT", "")).lower() in {"0", "false", "off"}
    legacy_protocol_off = str(env.get("ALLRIGHT_MASCOT_PROTOCOL", "")).lower() == "off"
    if disabled or legacy_protocol_off:
        return ""
    force = str(env.get("ALLRIGHT_FORCE_MASCOT", "")).lower() in {"1", "true", "on"}
    if not force and not getattr(stream, "isatty", lambda: False)():
        return ""
    return mascot_art(state)


def print_mascot(state: str, stream=None, env=None) -> None:
    """Print a mascot only when the active terminal supports a useful rendering."""
    stream = stream or sys.stdout
    rendered = render_mascot(state, stream=stream, env=env)
    if rendered:
        print(rendered, file=stream)
