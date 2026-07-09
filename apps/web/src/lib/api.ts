export type ApprovalStatus = "pending" | "approved" | "rejected"
export type CommandStatus = "started" | "waiting_approval" | "completed" | "failed" | "rejected" | "timeout"
export type RunStatus = "started" | "completed" | "failed" | "cancelled"
export type AgentSessionStatus = "active" | "waiting_user_input" | "completed" | "failed" | "cancelled"
export type SessionMessageRole = "user" | "agent" | "system"
export type EventType =
  | "run_created"
  | "agent_prompt"
  | "plan_created"
  | "command_started"
  | "command_output"
  | "command_finished"
  | "policy_decision"
  | "file_changed"
  | "network_evidence"
  | "approval_required"
  | "approval_approved"
  | "approval_rejected"
  | "run_completed"
  | "run_failed"

export type Approval = {
  id: string
  tool: string
  argv: string[]
  command_line: string
  cwd: string
  risk_level: string
  reason: string
  status: ApprovalStatus
  created_at: string
  resolved_at: string | null
  resolved_by: string | null
  comment: string | null
}

export type CommandRecord = {
  id: string
  run_id: string | null
  tool: string
  argv: string[]
  command_line: string
  cwd: string
  command_origin: "agent_tool" | "runtime_internal" | "external_binary" | string
  risk_level: string
  requires_approval: boolean
  approval_id: string | null
  status: CommandStatus
  exit_code: number | null
  duration_ms: number | null
  started_at: string
  finished_at: string | null
}

export type RunRecord = {
  id: string
  session_id: string | null
  source: string
  cwd: string
  status: RunStatus
  started_at: string
  finished_at: string | null
}

export type RunSummary = {
  run_id: string
  source: string
  status: RunStatus
  cwd: string
  total_commands: number
  agent_tool_commands: number
  runtime_internal_commands: number
  governed_commands: number
  successful_governed_commands: number
  successful_commands: number
  failed_commands: number
  approval_count: number
  rejected_count: number
  risky_command_count: number
  total_duration_ms: number
  failure_summary: {
    failed_command: string
    exit_code: number | null
    reason: string
    suggested_next_action: string
  } | null
}

export type MicaEvent = {
  id: string
  run_id: string | null
  command_id: string | null
  approval_id: string | null
  event_type: EventType
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export type DockerExecuteResponse = {
  run: RunRecord
  command: CommandRecord
  result: {
    exit_code: number
    stdout: string
    stderr: string
    duration_ms: number
    image: string
    workspace: string
    network_mode: "none" | "bridge" | string
    command: string[]
  }
}

export type AgentRunResponse = {
  run: RunRecord
  prompt: string
  agent_type: string
  runner_mode: string
  planned_command: string[]
}

export type AgentAvailability = {
  agent_type: string
  available: boolean
  executable: string | null
  reason: string | null
}

export type AgentListResponse = {
  agents: AgentAvailability[]
}

export type AgentSession = {
  id: string
  title: string
  workspace: string
  agent_type: string
  runner_mode: string
  status: AgentSessionStatus
  created_at: string
  updated_at: string
  last_run_id: string | null
  external_session_id: string | null
  transport: string | null
  backend_url: string | null
  summary: string | null
}

export type SessionMessage = {
  id: string
  session_id: string
  run_id: string | null
  role: SessionMessageRole
  content: string
  message_metadata: Record<string, unknown>
  created_at: string
}

export type SessionContinueResponse = {
  session: AgentSession
  run: RunRecord
  message: SessionMessage
  planned_command: string[]
}

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `API request failed with ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export function formatDate(value: string | null) {
  if (!value) return "-"
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

export function formatDuration(ms: number | null | undefined) {
  if (!ms) return "-"
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
