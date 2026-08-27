"""Crash-safe persistence helpers and deterministic fault injection.

Production callers leave ``fault_injector`` unset. Tests can arm a
``FaultInjector`` at a named durability boundary to simulate a process dying
between two filesystem operations without using ``os._exit``.
"""

import json
import os
import tempfile
from pathlib import Path


class InjectedCrash(RuntimeError):
    """Raised by tests at a named persistence boundary."""

    def __init__(self, point):
        self.point = str(point)
        super().__init__(f"injected crash at {self.point}")


class FaultInjector:
    """Small, opt-in fault injector used by crash-recovery tests."""

    def __init__(self, *points):
        self.points = {str(point) for point in points}
        self.hits = []

    def arm(self, *points):
        self.points.update(str(point) for point in points)

    def disarm(self, *points):
        if points:
            self.points.difference_update(str(point) for point in points)
        else:
            self.points.clear()

    def __call__(self, point, **context):
        point = str(point)
        self.hits.append({"point": point, **context})
        if point in self.points:
            raise InjectedCrash(point)


def hit_fault(fault_injector, point, **context):
    if fault_injector is not None:
        fault_injector(point, **context)


def _fsync_parent(path):
    """Best-effort directory sync; Windows does not expose a portable form."""

    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_atomic(path, payload, *, fault_injector=None, fault_prefix="atomic"):
    """Durably replace one JSON file while preserving its previous version.

    A crash before ``replace`` leaves the old destination intact. A crash after
    ``replace`` may report an ambiguous result to the caller, but the new JSON
    is already complete and loadable.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        hit_fault(
            fault_injector,
            f"{fault_prefix}.before_replace",
            path=str(path),
            temp_path=str(temp_path),
        )
        os.replace(temp_path, path)
        temp_path = None
        hit_fault(fault_injector, f"{fault_prefix}.after_replace", path=str(path))
        _fsync_parent(path.parent)
        hit_fault(fault_injector, f"{fault_prefix}.after_parent_fsync", path=str(path))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return path


def repair_jsonl_tail(path, *, validate_interior=True):
    """Remove only an incomplete or invalid final JSONL record.

    Corruption in the middle of the trace is not silently hidden and raises a
    ``ValueError``. A final partial record is the expected shape of an abrupt
    append crash, so it is truncated back to the last verified newline.
    """

    path = Path(path)
    if not path.exists():
        return 0
    payload = path.read_bytes()
    if not payload:
        return 0
    if not validate_interior:
        if payload.endswith(b"\n"):
            return 0
        verified_bytes = payload.rfind(b"\n") + 1
        removed_bytes = len(payload) - verified_bytes
        with path.open("r+b") as handle:
            handle.truncate(verified_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        return removed_bytes
    lines = payload.splitlines(keepends=True)
    verified_bytes = 0
    for index, line in enumerate(lines):
        is_last = index == len(lines) - 1
        has_newline = line.endswith(b"\n")
        if not has_newline:
            if not is_last:
                raise ValueError(f"trace contains an incomplete record before the tail: {path}")
            break
        try:
            json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if not is_last:
                raise ValueError(f"trace contains a corrupt interior record: {path}") from exc
            break
        verified_bytes += len(line)
    else:
        return 0

    removed_bytes = len(payload) - verified_bytes
    with path.open("r+b") as handle:
        handle.truncate(verified_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    return removed_bytes


def append_jsonl(path, event, *, fault_injector=None, fault_prefix="trace"):
    """Append one durable JSONL record and expose crash boundaries to tests."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The hot append path checks only for a non-newline-terminated tail. Full
    # interior validation remains available when a trace is explicitly loaded.
    repair_jsonl_tail(path, validate_interior=False)
    encoded = (json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    hit_fault(fault_injector, f"{fault_prefix}.before_append", path=str(path))
    descriptor = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if fault_injector is not None and len(encoded) > 1:
            split_at = max(1, len(encoded) // 2)
            written = os.write(descriptor, encoded[:split_at])
            if written != split_at:
                raise OSError("short JSONL prefix write")
            hit_fault(
                fault_injector,
                f"{fault_prefix}.after_partial_write",
                path=str(path),
                bytes_written=written,
            )
            remainder = encoded[split_at:]
            written = os.write(descriptor, remainder)
            if written != len(remainder):
                raise OSError("short JSONL suffix write")
        else:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise OSError("short JSONL write")
        hit_fault(fault_injector, f"{fault_prefix}.after_write", path=str(path))
        os.fsync(descriptor)
        hit_fault(fault_injector, f"{fault_prefix}.after_fsync", path=str(path))
    finally:
        os.close(descriptor)
    return path
