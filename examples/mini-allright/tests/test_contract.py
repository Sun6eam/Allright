import subprocess
import sys
from pathlib import Path

import mini_allright


def test_mini_allright_module_and_public_exports():
    assert mini_allright.Allright is not None
    assert mini_allright.FakeModelClient is not None
    assert not hasattr(mini_allright, "MiniAgent")
    result = subprocess.run([sys.executable, "-m", "mini_allright", "--help"], capture_output=True, text=True, check=True)
    assert "Teaching-sized Allright agent harness" in result.stdout


def test_readme_main_mapping_points_to_existing_files():
    repo_root = Path(__file__).resolve().parents[3]
    main_files = [
        "allright/cli.py",
        "allright/runtime.py",
        "allright/agent_loop.py",
        "allright/context_manager.py",
        "allright/providers/clients.py",
        "allright/tool_executor.py",
        "allright/tools.py",
        "allright/task_state.py",
        "allright/run_store.py",
        "allright/workspace.py",
    ]
    for path in main_files:
        assert (repo_root / path).exists()
