import json
from pathlib import Path
from unittest.mock import patch

from allright.cli import main
from allright.doctor import (
    FAIL,
    PASS,
    DiagnosticResult,
    DoctorReport,
    check_provider,
    check_storage,
    run_doctor,
)

KEY_NAMES = (
    "ALLRIGHT_DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY",
    "ALLRIGHT_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "ALLRIGHT_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "ALLRIGHT_RIGHT_CODES_API_KEY",
    "RIGHT_CODES_API_KEY",
)


def clear_provider_keys(monkeypatch):
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_provider_check_reports_missing_key_without_exposing_values(monkeypatch):
    clear_provider_keys(monkeypatch)

    result = check_provider("deepseek")

    assert result.status == FAIL
    assert "ALLRIGHT_DEEPSEEK_API_KEY" in result.message
    assert result.details["api_key_configured"] is False


def test_provider_check_accepts_configured_key_but_never_returns_it(monkeypatch):
    clear_provider_keys(monkeypatch)
    monkeypatch.setenv("ALLRIGHT_DEEPSEEK_API_KEY", "sk-super-secret-value")

    result = check_provider("deepseek")
    rendered = json.dumps(result.__dict__)

    assert result.status == PASS
    assert result.details["api_key_configured"] is True
    assert "sk-super-secret-value" not in rendered


def test_ollama_provider_does_not_require_api_key(monkeypatch):
    clear_provider_keys(monkeypatch)

    result = check_provider("ollama", base_url="http://127.0.0.1:11434")

    assert result.status == PASS
    assert "does not require" in result.message


def test_provider_check_rejects_invalid_endpoint(monkeypatch):
    clear_provider_keys(monkeypatch)
    monkeypatch.setenv("ALLRIGHT_DEEPSEEK_API_KEY", "configured")

    result = check_provider("deepseek", base_url="not-a-url")

    assert result.status == FAIL
    assert "valid HTTP(S) URL" in result.message


def test_storage_check_leaves_no_probe_file(tmp_path):
    before = set(tmp_path.iterdir())

    result = check_storage(tmp_path)

    assert result.status == PASS
    assert set(tmp_path.iterdir()) == before


def test_report_exit_codes_and_json_are_stable(tmp_path):
    passed = DiagnosticResult("one", PASS, "ok")
    failed = DiagnosticResult("two", FAIL, "bad")

    report = DoctorReport("deepseek", str(tmp_path), (passed, failed))
    payload = json.loads(report.render_json())

    assert report.exit_code == 2
    assert payload["status"] == FAIL
    assert payload["exit_code"] == 2
    assert payload["results"][1]["name"] == "two"


def test_run_doctor_returns_named_checks(tmp_path, monkeypatch):
    clear_provider_keys(monkeypatch)

    report = run_doctor(tmp_path, "ollama")

    names = [result.name for result in report.results]
    assert names == ["python", "workspace", "git", "env", "provider", "shell", "storage"]
    assert all("secret" not in json.dumps(result.__dict__).lower() for result in report.results)


def test_cli_doctor_json_does_not_build_agent(tmp_path, monkeypatch, capsys):
    clear_provider_keys(monkeypatch)
    monkeypatch.setenv("ALLRIGHT_PROVIDER", "ollama")

    with patch("allright.cli.build_agent") as build_agent:
        exit_code = main(["doctor", "--cwd", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code in {0, 1}
    assert payload["provider"] == "ollama"
    assert payload["workspace"] == str(Path(tmp_path).resolve())
    build_agent.assert_not_called()


def test_cli_doctor_missing_deepseek_key_returns_failure(tmp_path, monkeypatch, capsys):
    clear_provider_keys(monkeypatch)
    monkeypatch.setenv("ALLRIGHT_PROVIDER", "deepseek")

    exit_code = main(["doctor", "--cwd", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == FAIL
    assert any(item["name"] == "provider" and item["status"] == FAIL for item in payload["results"])


def test_cli_doctor_does_not_echo_malformed_env_content(tmp_path, monkeypatch, capsys):
    secret = "sk-secret-without-an-equals-sign"
    (tmp_path / ".env").write_text(secret + "\n", encoding="utf-8")

    exit_code = main(["doctor", "--cwd", str(tmp_path), "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 2
    assert payload["status"] == FAIL
    assert secret not in output
    assert payload["error"] == "environment configuration could not be loaded (ValueError)"
