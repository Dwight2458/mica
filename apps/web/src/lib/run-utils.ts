import type { EventType, MicaEvent } from "@/lib/api"

export const runEventTypes: EventType[] = [
  "run_created",
  "agent_prompt",
  "plan_created",
  "command_started",
  "command_output",
  "command_finished",
  "policy_decision",
  "file_changed",
  "network_evidence",
  "approval_required",
  "approval_approved",
  "approval_rejected",
  "run_completed",
  "run_failed",
]

export function mergeEvents(current: MicaEvent[], nextEvents: MicaEvent[]): MicaEvent[] {
  const byId = new Map(current.map((event) => [event.id, event]))
  nextEvents.forEach((event) => byId.set(event.id, event))
  return Array.from(byId.values()).sort(
    (left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
  )
}

export function rawEvent(event: MicaEvent): Record<string, unknown> | null {
  const value = event.payload.raw_event
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function rawPart(event: MicaEvent): Record<string, unknown> | null {
  const raw = rawEvent(event)
  const value = raw?.part
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function rawItem(event: MicaEvent): Record<string, unknown> | null {
  const raw = rawEvent(event)
  const value = raw?.item
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

export function agentOutputText(event: MicaEvent): string | null {
  if (event.event_type !== "command_output") return null
  const raw = rawEvent(event)
  if (!raw) {
    return typeof event.payload.text === "string" && event.payload.stream === "stdout" ? event.payload.text : null
  }
  const rawType = raw.type
  const part = rawPart(event)
  const item = rawItem(event)
  if (rawType === "text" && typeof part?.text === "string") return part.text
  if (rawType === "tool_use") {
    const state = part?.state
    if (state && typeof state === "object" && !Array.isArray(state)) {
      const output = (state as Record<string, unknown>).output
      if (typeof output === "string") return output
      const metadata = (state as Record<string, unknown>).metadata
      if (metadata && typeof metadata === "object" && !Array.isArray(metadata)) {
        const metadataOutput = (metadata as Record<string, unknown>).output
        if (typeof metadataOutput === "string") return metadataOutput
      }
    }
  }
  if (item?.type === "agent_message" && typeof item.text === "string") return item.text
  return null
}

export function isLowSignalAgentEvent(event: MicaEvent): boolean {
  if (event.event_type !== "command_output") return false
  const raw = rawEvent(event)
  if (!raw) return false
  const rawType = raw.type
  if (
    rawType === "step_start" ||
    rawType === "step_finish" ||
    rawType === "thread.started" ||
    rawType === "turn.started" ||
    rawType === "turn.completed" ||
    rawType === "session_configured"
  ) {
    return true
  }
  const item = rawItem(event)
  return item?.type === "error" && typeof item.message === "string" && item.message.includes("Skill descriptions")
}

export function eventPayloadString(event: MicaEvent, key: string): string | null {
  const value = event.payload[key]
  return typeof value === "string" ? value : null
}

export function runPromptFromEvents(events: MicaEvent[]): string | null {
  const promptEvent = events.find((event) => event.event_type === "agent_prompt")
  return promptEvent ? eventPayloadString(promptEvent, "prompt") ?? promptEvent.message : null
}

