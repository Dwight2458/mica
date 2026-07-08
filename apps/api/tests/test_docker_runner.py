from __future__ import annotations

import os
from pathlib import Path


def test_docker_runner_executes_command_with_safe_defaults(tmp_path: Path) -> None:
    from app.runners.docker_runner import DockerRunner

    fakebin = tmp_path / "fakebin"
    workspace = tmp_path / "workspace"
    args_path = tmp_path / "docker-args.txt"
    fakebin.mkdir()
    workspace.mkdir()

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo %* > \"%MICA_FAKE_DOCKER_ARGS%\"",
                "echo runner-out",
                "echo runner-err 1>&2",
                "exit /b 7",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_FAKE_DOCKER_ARGS"] = str(args_path)
    runner = DockerRunner(docker_command=str(fakebin / "docker.cmd"), image="python:3.12-slim", env=env)

    result = runner.run(workspace=workspace, command=["python", "-c", "print('hello')"])

    assert result.exit_code == 7
    assert "runner-out" in result.stdout
    assert "runner-err" in result.stderr
    assert result.duration_ms >= 0
    assert result.network_mode == "none"
    assert result.workspace == workspace.resolve()

    docker_args = args_path.read_text(encoding="utf-8")
    assert "run" in docker_args
    assert "--rm" in docker_args
    assert "--network none" in docker_args
    assert "type=bind" in docker_args
    assert f"source={workspace.resolve()}" in docker_args
    assert "target=/workspace" in docker_args
    assert "-w /workspace" in docker_args
    assert "python:3.12-slim" in docker_args


def test_docker_runner_can_use_explicit_network_mode(tmp_path: Path) -> None:
    from app.runners.docker_runner import DockerRunner

    fakebin = tmp_path / "fakebin"
    workspace = tmp_path / "workspace"
    args_path = tmp_path / "docker-args.txt"
    fakebin.mkdir()
    workspace.mkdir()

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo %* > \"%MICA_FAKE_DOCKER_ARGS%\"",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_FAKE_DOCKER_ARGS"] = str(args_path)
    runner = DockerRunner(
        docker_command=str(fakebin / "docker.cmd"),
        image="python:3.12-slim",
        network_mode="bridge",
        env=env,
    )

    result = runner.run(workspace=workspace, command=["python", "-V"])

    assert result.network_mode == "bridge"
    assert "--network bridge" in args_path.read_text(encoding="utf-8")


def test_docker_runner_rejects_missing_workspace(tmp_path: Path) -> None:
    from app.runners.docker_runner import DockerRunner

    runner = DockerRunner(docker_command="docker", image="python:3.12-slim")

    try:
        runner.run(workspace=tmp_path / "missing", command=["python", "-V"])
    except FileNotFoundError as exc:
        assert "workspace does not exist" in str(exc)
    else:
        raise AssertionError("Expected missing workspace to raise FileNotFoundError")


def test_docker_runner_can_inject_proxy_shims_and_policy(tmp_path: Path) -> None:
    from app.runners.docker_runner import DockerProxyInjection, DockerRunner

    fakebin = tmp_path / "fakebin"
    workspace = tmp_path / "workspace"
    proxy_dir = tmp_path / "proxy"
    shim_dir = tmp_path / "docker-shims"
    policy_file = tmp_path / "policies" / "command-policy.json"
    args_path = tmp_path / "docker-args.txt"
    fakebin.mkdir()
    workspace.mkdir()
    proxy_dir.mkdir()
    shim_dir.mkdir()
    policy_file.parent.mkdir()
    policy_file.write_text('{"version":1,"rules":[]}', encoding="utf-8")

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo %* > \"%MICA_FAKE_DOCKER_ARGS%\"",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_FAKE_DOCKER_ARGS"] = str(args_path)
    runner = DockerRunner(
        docker_command=str(fakebin / "docker.cmd"),
        image="python:3.12-slim",
        env=env,
        proxy_injection=DockerProxyInjection(
            proxy_dir=proxy_dir,
            shim_dir=shim_dir,
            policy_file=policy_file,
            api_base_url="http://host.docker.internal:8000/api",
        ),
    )

    runner.run(workspace=workspace, command=["git", "status"])

    docker_args = args_path.read_text(encoding="utf-8")
    assert f"source={proxy_dir.resolve()},target=/mica/proxy,readonly" in docker_args
    assert f"source={shim_dir.resolve()},target=/mica/shims,readonly" in docker_args
    assert f"source={policy_file.resolve()},target=/mica/policies/command-policy.json,readonly" in docker_args
    assert "-e PYTHONPATH=/mica/proxy" in docker_args
    assert "-e MICA_API_BASE_URL=http://host.docker.internal:8000/api" in docker_args
    assert "-e MICA_POLICY_FILE=/mica/policies/command-policy.json" in docker_args
    assert "-e MICA_ORIGINAL_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" in docker_args
    assert "-e PATH=/mica/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" in docker_args


def test_docker_runner_can_inject_mica_run_id_for_container_proxy(tmp_path: Path) -> None:
    from app.runners.docker_runner import DockerProxyInjection, DockerRunner

    fakebin = tmp_path / "fakebin"
    workspace = tmp_path / "workspace"
    proxy_dir = tmp_path / "proxy"
    shim_dir = tmp_path / "docker-shims"
    policy_file = tmp_path / "policies" / "command-policy.json"
    args_path = tmp_path / "docker-args.txt"
    fakebin.mkdir()
    workspace.mkdir()
    proxy_dir.mkdir()
    shim_dir.mkdir()
    policy_file.parent.mkdir()
    policy_file.write_text('{"version":1,"rules":[]}', encoding="utf-8")

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo %* > \"%MICA_FAKE_DOCKER_ARGS%\"",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_FAKE_DOCKER_ARGS"] = str(args_path)
    runner = DockerRunner(
        docker_command=str(fakebin / "docker.cmd"),
        image="python:3.12-slim",
        env=env,
        proxy_injection=DockerProxyInjection(
            proxy_dir=proxy_dir,
            shim_dir=shim_dir,
            policy_file=policy_file,
            api_base_url="http://host.docker.internal:8000/api",
        ),
    )

    runner.run(workspace=workspace, command=["git", "push"], run_id="run-123")

    docker_args = args_path.read_text(encoding="utf-8")
    assert "-e MICA_RUN_ID=run-123" in docker_args


def test_docker_runner_streams_output_chunks_while_command_runs(tmp_path: Path) -> None:
    from app.runners.docker_runner import DockerRunner

    fakebin = tmp_path / "fakebin"
    workspace = tmp_path / "workspace"
    fakebin.mkdir()
    workspace.mkdir()

    (fakebin / "docker.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo first-line",
                "echo second-line",
                "echo error-line 1>&2",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    chunks: list[tuple[str, str]] = []
    runner = DockerRunner(docker_command=str(fakebin / "docker.cmd"), image="python:3.12-slim", env=env)

    result = runner.run(
        workspace=workspace,
        command=["python", "-c", "print('unused')"],
        on_output=lambda chunk: chunks.append((chunk.stream, chunk.text)),
    )

    assert result.exit_code == 0
    assert ("stdout", "first-line\n") in chunks
    assert ("stdout", "second-line\n") in chunks
    assert ("stderr", "error-line \n") in chunks


def test_linux_docker_shims_call_mica_proxy() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    for tool in ("git", "npm", "terraform", "kubectl"):
        shim = repo_root / "docker-shims" / tool
        assert shim.exists()
        content = shim.read_text(encoding="utf-8")
        assert "#!/usr/bin/env sh" in content
        assert f'python -m mica_proxy --tool {tool} -- "$@"' in content
