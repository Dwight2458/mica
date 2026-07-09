from __future__ import annotations

from enum import Enum


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CommandStatus(str, Enum):
    STARTED = "started"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class RunStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentSessionStatus(str, Enum):
    ACTIVE = "active"
    WAITING_USER_INPUT = "waiting_user_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionMessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class EventType(str, Enum):
    RUN_CREATED = "run_created"
    AGENT_PROMPT = "agent_prompt"
    PLAN_CREATED = "plan_created"
    COMMAND_STARTED = "command_started"
    COMMAND_OUTPUT = "command_output"
    COMMAND_FINISHED = "command_finished"
    POLICY_DECISION = "policy_decision"
    FILE_CHANGED = "file_changed"
    NETWORK_EVIDENCE = "network_evidence"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
