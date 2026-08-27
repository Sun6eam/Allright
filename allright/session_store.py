"""Session JSON persistence."""

import json
from pathlib import Path

from .persistence import write_json_atomic


class SessionStore:
    def __init__(self, root, fault_injector=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fault_injector = fault_injector

    def path(self, session_id):
        return self.root / f"{session_id}.json"

    def save(self, session):
        path = self.path(session["id"])
        return write_json_atomic(
            path,
            session,
            fault_injector=self.fault_injector,
            fault_prefix="session",
        )

    def load(self, session_id):
        return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None
