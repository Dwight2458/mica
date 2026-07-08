from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_verify_docker_isolation_uses_network_none_and_workspace_mount(tmp_path: Path) -> None:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    workdir = tmp_path / "workspace"
    report_path = tmp_path / "docker-spike.md"
    args_path = tmp_path / "docker-args.txt"

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo %* > \"%MICA_FAKE_DOCKER_ARGS%\"",
                "echo mica-docker-ok > \"%MICA_FAKE_WORKDIR%\\mica-docker-proof.txt\"",
                "echo mica-docker-ok",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_FAKE_DOCKER_ARGS"] = str(args_path)
    env["MICA_FAKE_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "verify-docker-isolation.ps1"),
            "-DockerCommand",
            "docker",
            "-Image",
            "python:3.12-slim",
            "-WorkDir",
            str(workdir),
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
    assert payload["status"] == "completed"
    assert payload["exit_code"] == 0
    assert payload["network_mode"] == "none"
    assert payload["workspace_mounted"] is True
    docker_args = args_path.read_text(encoding="utf-8")
    assert "run" in docker_args
    assert "--rm" in docker_args
    assert "--network none" in docker_args
    assert "type=bind" in docker_args
    assert "target=/workspace" in docker_args
    assert "-w /workspace" in docker_args
    report = report_path.read_text(encoding="utf-8")
    assert "network: none" in report
    assert "mounted workspace" in report
    assert str(workdir) in report
    assert "System.Collections.Hashtable" not in report
    assert "~~~text" in report
    assert "This is a spike, not a full Docker Runner" in report


def test_verify_docker_isolation_returns_2_when_docker_is_missing(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "verify-docker-isolation.ps1"),
            "-DockerCommand",
            "mica-missing-docker",
            "-WorkDir",
            str(tmp_path / "workspace"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Docker CLI was not found" in result.stderr
