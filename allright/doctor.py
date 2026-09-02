"""Local environment diagnostics for Allright.

The doctor command is intentionally offline and side-effect-light: it validates
the local runtime and provider configuration without sending prompts or API
keys over the network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import find_project_env, provider_env

PASS = "pass"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class DiagnosticResult:
    name: str
    status: str
    message: str
    details: dict[str, object] | None = None


@dataclass(frozen=True)
class DoctorReport:
    provider: str
    workspace: str
    results: tuple[DiagnosticResult, ...]

    @property
    def exit_code(self):
        if any(result.status == FAIL for result in self.results):
            return 2
        if any(result.status == WARN for result in self.results):
            return 1
        return 0

    def to_dict(self):
        return {
            "provider": self.provider,
            "workspace": self.workspace,
            "status": {0: PASS, 1: WARN, 2: FAIL}[self.exit_code],
            "exit_code": self.exit_code,
            "results": [asdict(result) for result in self.results],
        }

    def render_text(self):
        lines = [f"Allright doctor: {self.workspace}", f"Provider: {self.provider}", ""]
        for result in self.results:
            lines.append(f"[{result.status.upper():4}] {result.name}: {result.message}")
        lines.extend(("", f"Overall: {self.to_dict()['status'].upper()} (exit {self.exit_code})"))
        return "\n".join(lines)

    def render_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _result(name, status, message, **details):
    return DiagnosticResult(name, status, message, details or None)


def check_python():
    version = sys.version_info
    version_text = f"{version.major}.{version.minor}.{version.micro}"
    if version < (3, 10):
        return _result("python", FAIL, f"Python {version_text} is unsupported; use 3.10+", version=version_text)
    return _result("python", PASS, f"Python {version_text}", version=version_text)


def check_workspace(workspace):
    path = Path(workspace)
    if not path.exists():
        return _result("workspace", FAIL, "workspace does not exist", path=str(path))
    if not path.is_dir():
        return _result("workspace", FAIL, "workspace is not a directory", path=str(path))
    return _result("workspace", PASS, "workspace directory is available", path=str(path.resolve()))


def check_git(workspace):
    executable = shutil.which("git")
    if executable is None:
        return _result("git", FAIL, "git executable was not found on PATH")
    try:
        version = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()
        root = subprocess.run(
            [executable, "rev-parse", "--show-toplevel"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return _result("git", WARN, "git is installed, but the workspace is not a readable Git repository")
    return _result("git", PASS, f"{version}; repository detected", repo_root=root)


def check_env(workspace):
    env_path = find_project_env(workspace)
    if env_path is None:
        return _result("env", WARN, ".env was not found; shell environment and defaults will be used")
    return _result("env", PASS, f"project environment found at {env_path}", path=str(env_path))


def _valid_url(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_provider(provider, *, base_url=None):
    if provider == "ollama":
        endpoint = base_url or provider_env("ALLRIGHT_OLLAMA_HOST", default="http://127.0.0.1:11434")
        if not _valid_url(endpoint):
            return _result("provider", FAIL, "Ollama host is not a valid HTTP(S) URL", provider=provider)
        return _result("provider", PASS, "Ollama does not require an API key", provider=provider, endpoint=endpoint)

    provider_config = {
        "deepseek": (
            "ALLRIGHT_DEEPSEEK_API_KEY",
            ("DEEPSEEK_API_KEY",),
            "ALLRIGHT_DEEPSEEK_API_BASE",
            ("DEEPSEEK_API_BASE",),
            "https://api.deepseek.com/anthropic",
        ),
        "openai": (
            "ALLRIGHT_OPENAI_API_KEY",
            ("OPENAI_API_KEY", "ALLRIGHT_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY"),
            "ALLRIGHT_OPENAI_API_BASE",
            ("OPENAI_API_BASE",),
            "https://www.right.codes/codex/v1",
        ),
        "anthropic": (
            "ALLRIGHT_ANTHROPIC_API_KEY",
            ("ANTHROPIC_API_KEY", "ALLRIGHT_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY"),
            "ALLRIGHT_ANTHROPIC_API_BASE",
            ("ANTHROPIC_API_BASE",),
            "https://www.right.codes/claude/v1",
        ),
    }
    if provider not in provider_config:
        return _result("provider", FAIL, f"unknown provider: {provider}")
    key_name, legacy_keys, base_name, legacy_bases, default_base = provider_config[provider]
    endpoint = base_url or provider_env(base_name, legacy_bases, default_base)
    if not _valid_url(endpoint):
        return _result("provider", FAIL, "provider base URL is not a valid HTTP(S) URL", provider=provider)
    if not provider_env(key_name, legacy_keys):
        return _result(
            "provider",
            FAIL,
            f"API key is missing; configure {key_name} in .env",
            provider=provider,
            endpoint=endpoint,
            api_key_configured=False,
        )
    return _result(
        "provider",
        PASS,
        "provider endpoint and API key are configured",
        provider=provider,
        endpoint=endpoint,
        api_key_configured=True,
    )


def check_shell():
    candidates = [os.environ.get("COMSPEC"), "pwsh", "powershell"] if os.name == "nt" else [os.environ.get("SHELL"), "sh"]
    for candidate in candidates:
        if candidate and (Path(candidate).exists() or shutil.which(candidate)):
            return _result("shell", PASS, f"shell available: {candidate}")
    return _result("shell", FAIL, "no supported shell executable was found")


def check_storage(workspace):
    path = Path(workspace)
    if not path.is_dir():
        return _result("storage", FAIL, "workspace is unavailable, so local state cannot be tested")
    try:
        with tempfile.NamedTemporaryFile(prefix=".allright-doctor-", dir=path, delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
    except OSError as exc:
        return _result("storage", FAIL, f"workspace is not writable: {type(exc).__name__}")
    return _result("storage", PASS, "workspace supports temporary state writes")


def run_doctor(workspace, provider, *, base_url=None):
    path = Path(workspace).resolve()
    results = (
        check_python(),
        check_workspace(path),
        check_git(path),
        check_env(path),
        check_provider(provider, base_url=base_url),
        check_shell(),
        check_storage(path),
    )
    return DoctorReport(provider=provider, workspace=str(path), results=results)
