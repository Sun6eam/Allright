import json

import pytest

from allright import Allright, FakeModelClient, WorkspaceContext
from allright.checkpoint import CHECKPOINT_FULL_VALID_STATUS
from allright.persistence import FaultInjector, InjectedCrash, repair_jsonl_tail
from allright.run_store import RunStore
from allright.session_store import SessionStore
from allright.task_state import TaskState


def build_agent(tmp_path, session_store):
    (tmp_path / "README.md").write_text("crash recovery fixture\n", encoding="utf-8")
    return Allright(
        model_client=FakeModelClient([]),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=session_store,
        approval_policy="auto",
    )


def test_session_crash_before_replace_preserves_previous_json(tmp_path):
    root = tmp_path / ".allright" / "sessions"
    clean_store = SessionStore(root)
    clean_store.save({"id": "session_001", "generation": 1})
    injector = FaultInjector("session.before_replace")

    with pytest.raises(InjectedCrash, match="session.before_replace"):
        SessionStore(root, fault_injector=injector).save(
            {"id": "session_001", "generation": 2}
        )

    assert clean_store.load("session_001") == {"id": "session_001", "generation": 1}
    assert not list(root.glob("*.tmp"))


def test_session_crash_after_replace_leaves_new_json_loadable(tmp_path):
    root = tmp_path / ".allright" / "sessions"
    clean_store = SessionStore(root)
    clean_store.save({"id": "session_001", "generation": 1})
    injector = FaultInjector("session.after_replace")

    with pytest.raises(InjectedCrash, match="session.after_replace"):
        SessionStore(root, fault_injector=injector).save(
            {"id": "session_001", "generation": 2}
        )

    assert clean_store.load("session_001") == {"id": "session_001", "generation": 2}


def test_task_state_crash_before_replace_preserves_previous_snapshot(tmp_path):
    root = tmp_path / ".allright" / "runs"
    clean_store = RunStore(root)
    state = TaskState.create(
        run_id="run_001",
        task_id="task_001",
        user_request="Test interrupted persistence.",
    )
    clean_store.start_run(state)
    state.record_attempt()
    injector = FaultInjector("run.task_state.before_replace")

    with pytest.raises(InjectedCrash, match="run.task_state.before_replace"):
        RunStore(root, fault_injector=injector).write_task_state(state)

    persisted = clean_store.load_task_state(state.run_id)
    assert persisted["attempts"] == 0
    assert persisted["status"] == "running"


def test_partial_trace_tail_is_removed_before_next_append(tmp_path):
    root = tmp_path / ".allright" / "runs"
    clean_store = RunStore(root)
    state = TaskState.create(
        run_id="run_002",
        task_id="task_002",
        user_request="Test trace repair.",
    )
    clean_store.append_trace(state, {"event": "run_started", "sequence": 1})
    injector = FaultInjector("run.trace.after_partial_write")

    with pytest.raises(InjectedCrash, match="run.trace.after_partial_write"):
        RunStore(root, fault_injector=injector).append_trace(
            state,
            {"event": "tool_executed", "sequence": 2},
        )

    clean_store.append_trace(state, {"event": "run_recovered", "sequence": 3})

    assert clean_store.load_trace(state.run_id) == [
        {"event": "run_started", "sequence": 1},
        {"event": "run_recovered", "sequence": 3},
    ]


def test_trace_crash_after_fsync_keeps_complete_event(tmp_path):
    root = tmp_path / ".allright" / "runs"
    state = TaskState.create(
        run_id="run_003",
        task_id="task_003",
        user_request="Test durable trace event.",
    )
    injector = FaultInjector("run.trace.after_fsync")

    with pytest.raises(InjectedCrash, match="run.trace.after_fsync"):
        RunStore(root, fault_injector=injector).append_trace(
            state,
            {"event": "checkpoint_created", "sequence": 1},
        )

    assert RunStore(root).load_trace(state.run_id) == [
        {"event": "checkpoint_created", "sequence": 1}
    ]


def test_trace_repair_refuses_to_hide_interior_corruption(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(
        '{"event": "first"}\nnot-json\n{"event": "third"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="corrupt interior record"):
        repair_jsonl_tail(path)


def test_checkpoint_save_crash_resumes_from_last_durable_checkpoint(tmp_path):
    injector = FaultInjector()
    store = SessionStore(tmp_path / ".allright" / "sessions", fault_injector=injector)
    agent = build_agent(tmp_path, store)
    first_state = TaskState.create(task_id="task_001", user_request="First goal")
    durable = agent.create_checkpoint(first_state, "First goal", trigger="test_baseline")

    injector.arm("session.before_replace")
    second_state = TaskState.create(task_id="task_002", user_request="Second goal")
    with pytest.raises(InjectedCrash, match="session.before_replace"):
        agent.create_checkpoint(second_state, "Second goal", trigger="test_crash")

    clean_store = SessionStore(store.root)
    resumed = Allright.from_session(
        model_client=FakeModelClient([]),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=clean_store,
        session_id=agent.session["id"],
        approval_policy="auto",
    )

    assert resumed.current_checkpoint()["checkpoint_id"] == durable["checkpoint_id"]
    assert resumed.resume_state["status"] == CHECKPOINT_FULL_VALID_STATUS
    assert resumed.current_checkpoint()["current_goal"] == "First goal"


def test_orphan_temporary_file_is_not_treated_as_latest_session(tmp_path):
    store = SessionStore(tmp_path / ".allright" / "sessions")
    store.save({"id": "session_001", "history": []})
    (store.root / "session_999.json.dead.tmp").write_text("{", encoding="utf-8")

    assert store.latest() == "session_001"
    assert json.loads(store.path("session_001").read_text(encoding="utf-8"))["id"] == "session_001"
