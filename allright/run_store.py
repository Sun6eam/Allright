"""运行工件落盘。

session.json 负责保存“可恢复的会话状态”；RunStore 负责保存“单次运行的审计工件”，
例如 task_state、trace 和 report。两者分开后，恢复现场和复盘证据不会混在一起。
"""

import json
from pathlib import Path

from .persistence import append_jsonl, repair_jsonl_tail, write_json_atomic


def _run_id(value):
    if hasattr(value, "run_id"):
        return value.run_id
    return str(value)


class RunStore:
    def __init__(self, root, fault_injector=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fault_injector = fault_injector

    def run_dir(self, run_id):
        return self.root / _run_id(run_id)

    def task_state_path(self, run_id):
        return self.run_dir(run_id) / "task_state.json"

    def trace_path(self, run_id):
        return self.run_dir(run_id) / "trace.jsonl"

    def report_path(self, run_id):
        return self.run_dir(run_id) / "report.json"

    def start_run(self, task_state):
        # 每次 ask() 都会生成一个 run 目录。
        # 这样一次用户请求对应一组独立工件，后续排查更容易。
        run_dir = self.run_dir(task_state)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state):
        path = self.task_state_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            path,
            task_state.to_dict(),
            fault_injector=self.fault_injector,
            fault_prefix="run.task_state",
        )
        return path

    def append_trace(self, task_state, event):
        path = self.trace_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 每条事件在 fsync 后才视为持久化。若进程在半行写入时崩溃，
        # 下一次追加会只移除损坏的尾记录，不会掩盖中间损坏。
        return append_jsonl(
            path,
            event,
            fault_injector=self.fault_injector,
            fault_prefix="run.trace",
        )

    def write_report(self, task_state, report):
        path = self.report_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            path,
            report,
            fault_injector=self.fault_injector,
            fault_prefix="run.report",
        )
        return path

    def load_task_state(self, task_id):
        return json.loads(self.task_state_path(task_id).read_text(encoding="utf-8"))

    def load_report(self, task_id):
        return json.loads(self.report_path(task_id).read_text(encoding="utf-8"))

    def load_trace(self, task_id, repair_tail=True):
        path = self.trace_path(task_id)
        if not path.exists():
            return []
        if repair_tail:
            repair_jsonl_tail(path)
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
