from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DOCKER_POLICY_PATH = Path(__file__).resolve().parents[4] / "policies" / "docker-policy.json"


@dataclass(frozen=True)
class DockerNetworkPolicy:
    allowed_modes: tuple[str, ...]
    require_host_callback_for_bridge: bool
    require_proxy_injection_for_bridge: bool


@dataclass(frozen=True)
class DockerPolicy:
    version: int
    network: DockerNetworkPolicy


def load_docker_policy(path: str | Path | None = None) -> DockerPolicy:
    policy_path = Path(path) if path is not None else DEFAULT_DOCKER_POLICY_PATH
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    network = raw.get("network", {})
    allowed_modes = tuple(str(mode) for mode in network.get("allowed_modes", ["none"]))
    return DockerPolicy(
        version=int(raw.get("version", 1)),
        network=DockerNetworkPolicy(
            allowed_modes=allowed_modes,
            require_host_callback_for_bridge=bool(network.get("require_host_callback_for_bridge", True)),
            require_proxy_injection_for_bridge=bool(network.get("require_proxy_injection_for_bridge", True)),
        ),
    )
