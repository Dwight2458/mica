from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_check_isolation_readiness_reports_docker_and_wsl2(tmp_path: Path) -> None:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    report_path = tmp_path / "isolation-readiness.md"

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                'if "%1"=="--version" echo Docker version 27.0.0, build fake& exit /b 0',
                'if "%1"=="info" echo Docker daemon reachable& exit /b 0',
                "exit /b 9",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )
    (fakebin / "wsl.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                'if "%1"=="--status" echo Default Version: 2& exit /b 0',
                'if "%1"=="-l" echo Ubuntu Running 2& exit /b 0',
                "exit /b 9",
            ]
        )
        + "\r\n",
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
            str(ROOT / "scripts" / "check-isolation-readiness.ps1"),
            "-DockerCommand",
            "docker",
            "-WslCommand",
            "wsl",
            "-ReportPath",
            str(report_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["docker"]["installed"] is True
    assert payload["docker"]["daemon_reachable"] is True
    assert payload["wsl"]["installed"] is True
    assert payload["wsl"]["wsl2_available"] is True
    assert payload["recommended_next_provider"] == "docker"
    report = report_path.read_text(encoding="utf-8")
    assert "Docker daemon reachable" in report
    assert "WSL2 available" in report
    assert "Local PATH shim mode remains non-sandboxed" in report


def test_check_isolation_readiness_handles_missing_providers(tmp_path: Path) -> None:
    report_path = tmp_path / "missing-readiness.md"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "check-isolation-readiness.ps1"),
            "-DockerCommand",
            "mica-missing-docker",
            "-WslCommand",
            "mica-missing-wsl",
            "-ReportPath",
            str(report_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["docker"]["installed"] is False
    assert payload["wsl"]["installed"] is False
    assert payload["recommended_next_provider"] == "local-only"
    assert "No strong isolation provider is currently ready" in report_path.read_text(encoding="utf-8")


def test_check_isolation_readiness_normalizes_null_padded_wsl_output(tmp_path: Path) -> None:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()

    (fakebin / "wsl.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "powershell -NoProfile -Command \"$n=[char]0; [Console]::Out.Write('Ubuntu'+$n+' Running'+$n+' 2'+$n)\"",
                "exit /b 0",
            ]
        )
        + "\r\n",
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
            str(ROOT / "scripts" / "check-isolation-readiness.ps1"),
            "-DockerCommand",
            "mica-missing-docker",
            "-WslCommand",
            "wsl",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["wsl"]["installed"] is True
    assert payload["wsl"]["wsl2_available"] is True
    assert payload["recommended_next_provider"] == "wsl2"
