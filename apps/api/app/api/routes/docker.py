from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import SessionDep
from app.runners.docker_runner import DockerProxyInjection, DockerRunner
from app.schemas.commands import CommandRecordRead
from app.schemas.docker import DockerExecuteRequest, DockerExecuteResponse, DockerRunResultRead
from app.schemas.runs import RunRecordRead
from app.services.docker_execution_service import DockerExecutionService, DockerRunnerProtocol
from app.services.docker_policy import DockerPolicy, load_docker_policy

router = APIRouter()


def get_docker_runner(request: Request, payload: DockerExecuteRequest) -> DockerRunnerProtocol:
    configured_runner = getattr(request.app.state, "docker_runner", None)
    if configured_runner is not None:
        return configured_runner
    return DockerRunner(
        image=payload.image,
        network_mode=payload.network_mode,
        proxy_injection=build_proxy_injection(payload) if payload.inject_proxy else None,
    )


def build_proxy_injection(payload: DockerExecuteRequest) -> DockerProxyInjection:
    repo_root = Path(__file__).resolve().parents[5]
    return DockerProxyInjection(
        proxy_dir=repo_root / "proxy",
        shim_dir=repo_root / "docker-shims",
        policy_file=repo_root / "policies" / "command-policy.json",
        api_base_url=payload.api_base_url,
    )


@router.post("/docker/execute", response_model=DockerExecuteResponse, status_code=status.HTTP_201_CREATED)
def execute_docker_command(
    payload: DockerExecuteRequest,
    request: Request,
    session: SessionDep,
) -> DockerExecuteResponse:
    policy_decision = enforce_network_policy(payload, load_policy_for_request(request))
    evidence = DockerExecutionService(session, runner=get_docker_runner(request, payload)).execute(
        workspace=payload.workspace,
        command=payload.command,
        policy_decision=policy_decision,
    )
    return DockerExecuteResponse(
        run=RunRecordRead.model_validate(evidence.run),
        command=CommandRecordRead.model_validate(evidence.command),
        result=DockerRunResultRead(
            exit_code=evidence.result.exit_code,
            stdout=evidence.result.stdout,
            stderr=evidence.result.stderr,
            duration_ms=evidence.result.duration_ms,
            image=evidence.result.image,
            workspace=str(evidence.result.workspace),
            network_mode=evidence.result.network_mode,
            command=list(evidence.result.command),
        ),
    )


def load_policy_for_request(request: Request) -> DockerPolicy:
    configured_policy_path = getattr(request.app.state, "docker_policy_path", None)
    return load_docker_policy(configured_policy_path)


def enforce_network_policy(payload: DockerExecuteRequest, policy: DockerPolicy) -> dict[str, object]:
    if payload.network_mode not in policy.network.allowed_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Docker network_mode={payload.network_mode} is not allowed by Docker policy.",
        )
    if (
        payload.network_mode == "bridge"
        and policy.network.require_host_callback_for_bridge
        and not payload.allow_host_callback
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Docker network_mode=bridge requires allow_host_callback=true because the container can reach "
                "host services such as the Mica approval API."
            ),
        )
    if (
        payload.network_mode == "bridge"
        and policy.network.require_proxy_injection_for_bridge
        and not payload.inject_proxy
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Docker network_mode=bridge requires inject_proxy=true because bridge mode is reserved for "
                "containerized mica-proxy approval callbacks."
            ),
        )
    return {
        "policy": "docker-network",
        "decision": "allowed",
        "network_mode": payload.network_mode,
        "allowed_modes": list(policy.network.allowed_modes),
        "allow_host_callback": payload.allow_host_callback,
        "inject_proxy": payload.inject_proxy,
        "require_host_callback_for_bridge": policy.network.require_host_callback_for_bridge,
        "require_proxy_injection_for_bridge": policy.network.require_proxy_injection_for_bridge,
        "reason": "network_mode is allowed by Docker policy",
    }
