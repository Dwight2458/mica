from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_probe_scripts_exit_2_when_cli_is_missing(tmp_path: Path) -> None:
    missing_command = "mica-definitely-missing-cli"
    scripts = [
        ("probe-codex.ps1", "-CodexCommand"),
        ("probe-claude.ps1", "-ClaudeCommand"),
        ("probe-gemini.ps1", "-GeminiCommand"),
    ]

    for script_name, command_param in scripts:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / script_name),
                command_param,
                missing_command,
                "-ProbeLog",
                str(tmp_path / f"{script_name}.jsonl"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 2, result.stderr


def test_probe_codex_records_expected_shim_hits(tmp_path: Path) -> None:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    probe_log = tmp_path / "codex-probe.jsonl"

    (fakebin / "codex.cmd").write_text(
        "\r\n".join(
                [
                    "@echo off",
                    'if not "%1"=="exec" exit /b 9',
                    'if "%2"=="--ask-for-approval" exit /b 8',
                    "call git status",
                "call npm -v",
                "call terraform --version",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )
    for tool in ["git", "npm", "terraform"]:
        (fakebin / f"{tool}.cmd").write_text(
            f"@echo off\r\necho REAL_{tool.upper()} %*\r\nexit /b 0\r\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "probe-codex.ps1"),
            "-CodexCommand",
            "codex",
            "-ProbeLog",
            str(probe_log),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "REAL_GIT status" in result.stdout
    assert "REAL_NPM -v" in result.stdout
    assert "REAL_TERRAFORM --version" in result.stdout

    events = [json.loads(line) for line in probe_log.read_text(encoding="utf-8").splitlines()]
    assert [event["tool"] for event in events] == ["git", "npm", "terraform"]
    assert "Mica Codex probe summary:" in result.stdout
    assert '"hit_rate": 1.0' in result.stdout


def test_probe_claude_records_expected_shim_hits(tmp_path: Path) -> None:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    probe_log = tmp_path / "claude-probe.jsonl"

    (fakebin / "claude.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                'if not "%1"=="-p" exit /b 9',
                "call git status",
                "call npm -v",
                "call terraform --version",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )
    for tool in ["git", "npm", "terraform"]:
        (fakebin / f"{tool}.cmd").write_text(
            f"@echo off\r\necho REAL_{tool.upper()} %*\r\nexit /b 0\r\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "probe-claude.ps1"),
            "-ClaudeCommand",
            "claude",
            "-ProbeLog",
            str(probe_log),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "REAL_GIT status" in result.stdout
    assert "REAL_NPM -v" in result.stdout
    assert "REAL_TERRAFORM --version" in result.stdout

    events = [json.loads(line) for line in probe_log.read_text(encoding="utf-8").splitlines()]
    assert [event["tool"] for event in events] == ["git", "npm", "terraform"]
    assert "Mica Claude Code probe summary:" in result.stdout
    assert '"hit_rate": 1.0' in result.stdout


def test_probe_gemini_records_expected_shim_hits(tmp_path: Path) -> None:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    probe_log = tmp_path / "gemini-probe.jsonl"

    (fakebin / "gemini.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                'if not "%1"=="-p" exit /b 9',
                "call git status",
                "call npm -v",
                "call terraform --version",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )
    for tool in ["git", "npm", "terraform"]:
        (fakebin / f"{tool}.cmd").write_text(
            f"@echo off\r\necho REAL_{tool.upper()} %*\r\nexit /b 0\r\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "probe-gemini.ps1"),
            "-GeminiCommand",
            "gemini",
            "-ProbeLog",
            str(probe_log),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "REAL_GIT status" in result.stdout
    assert "REAL_NPM -v" in result.stdout
    assert "REAL_TERRAFORM --version" in result.stdout

    events = [json.loads(line) for line in probe_log.read_text(encoding="utf-8").splitlines()]
    assert [event["tool"] for event in events] == ["git", "npm", "terraform"]
    assert "Mica Gemini CLI probe summary:" in result.stdout
    assert '"hit_rate": 1.0' in result.stdout
