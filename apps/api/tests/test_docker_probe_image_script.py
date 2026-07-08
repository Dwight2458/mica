from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_build_docker_probe_image_invokes_docker_build(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    args_file = tmp_path / "docker-args.txt"
    fake_docker = fake_bin / "docker.cmd"
    fake_docker.write_text(
        "\n".join(
            [
                "@echo off",
                'echo %* > "%MICA_FAKE_DOCKER_ARGS%"',
                "echo fake docker build ok",
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["MICA_FAKE_DOCKER_ARGS"] = str(args_file)

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "build-docker-probe-image.ps1"),
            "-DockerCommand",
            "docker",
            "-Image",
            "mica-python-git:local",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    docker_args = args_file.read_text(encoding="utf-8")

    assert payload["status"] == "completed"
    assert payload["image"] == "mica-python-git:local"
    assert payload["exit_code"] == 0
    assert "build" in docker_args
    assert "-t mica-python-git:local" in docker_args
    assert "-f " in docker_args
    assert str(ROOT / "docker" / "mica-python-git.Dockerfile") in docker_args
    assert str(ROOT) in docker_args


def test_build_docker_probe_image_allows_docker_progress_on_stderr(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker.cmd"
    fake_docker.write_text(
        "\n".join(
            [
                "@echo off",
                "echo fake stdout",
                "echo fake buildkit progress 1>&2",
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "build-docker-probe-image.ps1"),
            "-DockerCommand",
            "docker",
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
    assert "fake buildkit progress" in "\n".join(payload["output"])
    assert "RemoteException" not in "\n".join(payload["output"])


def test_docker_probe_image_dockerfile_contains_python_git_and_certs() -> None:
    dockerfile = ROOT / "docker" / "mica-python-git.Dockerfile"

    contents = dockerfile.read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in contents
    assert "apt-get update" in contents
    assert "git" in contents
    assert "ca-certificates" in contents
    assert "rm -rf /var/lib/apt/lists/*" in contents
