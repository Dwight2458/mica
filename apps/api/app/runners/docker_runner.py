from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class DockerRunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    image: str
    workspace: Path
    network_mode: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class DockerOutputChunk:
    stream: str
    text: str


@dataclass(frozen=True)
class DockerProxyInjection:
    proxy_dir: Path
    shim_dir: Path
    policy_file: Path
    api_base_url: str
    container_proxy_dir: str = "/mica/proxy"
    container_shim_dir: str = "/mica/shims"
    container_policy_file: str = "/mica/policies/command-policy.json"
    original_path: str = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class DockerRunner:
    """Minimal Docker execution runner with conservative local defaults."""

    def __init__(
        self,
        *,
        docker_command: str = "docker",
        image: str = "python:3.12-slim",
        network_mode: str = "none",
        env: Mapping[str, str] | None = None,
        proxy_injection: DockerProxyInjection | None = None,
    ) -> None:
        if network_mode not in {"none", "bridge"}:
            raise ValueError("network_mode must be one of: none, bridge")
        self.docker_command = docker_command
        self.image = image
        self.network_mode = network_mode
        self.env = dict(env) if env is not None else os.environ.copy()
        self.proxy_injection = proxy_injection

    def run(
        self,
        *,
        workspace: str | Path,
        command: Sequence[str],
        run_id: str | None = None,
        on_output: Callable[[DockerOutputChunk], None] | None = None,
    ) -> DockerRunResult:
        workspace_path = Path(workspace).resolve()
        if not workspace_path.exists() or not workspace_path.is_dir():
            raise FileNotFoundError(f"workspace does not exist or is not a directory: {workspace_path}")
        if not command:
            raise ValueError("command must not be empty")

        docker_args = self._docker_args(workspace_path=workspace_path, command=command, run_id=run_id)
        if on_output is not None:
            return self._run_streaming(
                docker_args=docker_args,
                workspace_path=workspace_path,
                command=command,
                on_output=on_output,
            )

        started = time.perf_counter()
        completed = subprocess.run(
            docker_args,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)

        return DockerRunResult(
            exit_code=int(completed.returncode),
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
            image=self.image,
            workspace=workspace_path,
            network_mode=self.network_mode,
            command=tuple(command),
        )

    def _docker_args(self, *, workspace_path: Path, command: Sequence[str], run_id: str | None) -> list[str]:
        docker_args = [
            self.docker_command,
            "run",
            "--rm",
            "--network",
            self.network_mode,
            "--mount",
            f"type=bind,source={workspace_path},target=/workspace",
            *self._proxy_injection_args(run_id=run_id),
            "-w",
            "/workspace",
            self.image,
            *command,
        ]
        return docker_args

    def _run_streaming(
        self,
        *,
        docker_args: Sequence[str],
        workspace_path: Path,
        command: Sequence[str],
        on_output: Callable[[DockerOutputChunk], None],
    ) -> DockerRunResult:
        started = time.perf_counter()
        process = subprocess.Popen(
            docker_args,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        chunks: queue.Queue[DockerOutputChunk] = queue.Queue()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        def read_stream(stream_name: str, pipe: object) -> None:
            if pipe is None:
                return
            for line in iter(pipe.readline, ""):
                chunks.put(DockerOutputChunk(stream=stream_name, text=line))
            pipe.close()

        threads = [
            threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()

        while process.poll() is None or any(thread.is_alive() for thread in threads) or not chunks.empty():
            try:
                chunk = chunks.get(timeout=0.05)
            except queue.Empty:
                continue
            if chunk.stream == "stdout":
                stdout_parts.append(chunk.text)
            else:
                stderr_parts.append(chunk.text)
            on_output(chunk)

        for thread in threads:
            thread.join(timeout=1)
        while not chunks.empty():
            chunk = chunks.get()
            if chunk.stream == "stdout":
                stdout_parts.append(chunk.text)
            else:
                stderr_parts.append(chunk.text)
            on_output(chunk)

        duration_ms = int((time.perf_counter() - started) * 1000)

        return DockerRunResult(
            exit_code=int(process.returncode or 0),
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            duration_ms=duration_ms,
            image=self.image,
            workspace=workspace_path,
            network_mode=self.network_mode,
            command=tuple(command),
        )

    def _proxy_injection_args(self, *, run_id: str | None = None) -> list[str]:
        if self.proxy_injection is None:
            return []

        injection = self.proxy_injection
        proxy_dir = Path(injection.proxy_dir).resolve()
        shim_dir = Path(injection.shim_dir).resolve()
        policy_file = Path(injection.policy_file).resolve()
        container_path = f"{injection.container_shim_dir}:{injection.original_path}"

        args = [
            "--mount",
            f"type=bind,source={proxy_dir},target={injection.container_proxy_dir},readonly",
            "--mount",
            f"type=bind,source={shim_dir},target={injection.container_shim_dir},readonly",
            "--mount",
            f"type=bind,source={policy_file},target={injection.container_policy_file},readonly",
            "-e",
            f"PYTHONPATH={injection.container_proxy_dir}",
            "-e",
            f"MICA_API_BASE_URL={injection.api_base_url}",
            "-e",
            f"MICA_POLICY_FILE={injection.container_policy_file}",
            "-e",
            f"MICA_ORIGINAL_PATH={injection.original_path}",
            "-e",
            f"PATH={container_path}",
        ]
        if run_id:
            args.extend(["-e", f"MICA_RUN_ID={run_id}"])
        return args
