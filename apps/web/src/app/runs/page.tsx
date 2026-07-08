"use client"

import { type FormEvent, useCallback, useEffect, useState } from "react"

import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import {
  API_BASE_URL,
  apiRequest,
  formatDate,
  formatDuration,
  type AgentAvailability,
  type AgentListResponse,
  type AgentRunResponse,
  type CommandRecord,
  type DockerExecuteResponse,
  type EventType,
  type MicaEvent,
  type RunRecord,
  type RunSummary,
} from "@/lib/api"

const eventTypes: EventType[] = [
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

function mergeEvents(current: MicaEvent[], nextEvents: MicaEvent[]): MicaEvent[] {
  const byId = new Map(current.map((event) => [event.id, event]))
  nextEvents.forEach((event) => byId.set(event.id, event))
  return Array.from(byId.values()).sort(
    (left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
  )
}

type DockerRunForm = {
  workspace: string
  image: string
  command: string
  network_mode: "none" | "bridge"
  allow_host_callback: boolean
  inject_proxy: boolean
  api_base_url: string
}

type AgentRunForm = {
  prompt: string
  workspace: string
  agent_type: string
  runner_mode: "local" | "docker"
}

const defaultAgentRunForm: AgentRunForm = {
  prompt: "Check git status and summarize uncommitted changes.",
  workspace: "C:\\Users\\24582\\Projects\\mica",
  agent_type: "mock-agent",
  runner_mode: "local",
}

const defaultDockerRunForm: DockerRunForm = {
  workspace: "C:\\Users\\24582\\Projects\\mica",
  image: "python:3.12-slim",
  command: "[\"python\",\"-c\",\"print('hello from mica run')\"]",
  network_mode: "none",
  allow_host_callback: false,
  inject_proxy: false,
  api_base_url: "http://host.docker.internal:8000/api",
}

function parseCommand(value: string): string[] {
  const parsed = JSON.parse(value) as unknown
  if (!Array.isArray(parsed) || parsed.length === 0 || parsed.some((item) => typeof item !== "string")) {
    throw new Error("Command must be a non-empty JSON array of strings.")
  }
  return parsed
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({})
  const [events, setEvents] = useState<MicaEvent[]>([])
  const [commands, setCommands] = useState<CommandRecord[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [agentForm, setAgentForm] = useState<AgentRunForm>(defaultAgentRunForm)
  const [agents, setAgents] = useState<AgentAvailability[]>([
    { agent_type: "mock-agent", available: true, executable: "mock-agent", reason: null },
  ])
  const [agentSubmitStatus, setAgentSubmitStatus] = useState<string | null>(null)
  const [isSubmittingAgentRun, setIsSubmittingAgentRun] = useState(false)
  const [runForm, setRunForm] = useState<DockerRunForm>(defaultDockerRunForm)
  const [submitStatus, setSubmitStatus] = useState<string | null>(null)
  const [isSubmittingRun, setIsSubmittingRun] = useState(false)
  const [showRuntimeInternalTrace, setShowRuntimeInternalTrace] = useState(false)
  const hasActiveRuns = runs.some((run) => run.status === "started")
  const selectedRun = runs.find((run) => run.id === selectedRunId)
  const selectedRunStatus = selectedRun?.status

  const load = useCallback(async () => {
    try {
      const nextRuns = await apiRequest<RunRecord[]>("/runs")
      const nextSummaries = await Promise.all(
        nextRuns.map((run) => apiRequest<RunSummary>(`/runs/${run.id}/summary`))
      )
      setRuns(nextRuns)
      setSummaries(Object.fromEntries(nextSummaries.map((summary) => [summary.run_id, summary])))
      setSelectedRunId((current) => current ?? nextRuns[0]?.id ?? null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load runs")
    }
  }, [])

  const loadAgents = useCallback(async () => {
    try {
      const response = await apiRequest<AgentListResponse>("/agent-runs/agents")
      setAgents(response.agents)
      setAgentForm((current) => {
        const selected = response.agents.find((agent) => agent.agent_type === current.agent_type)
        if (selected?.available) return current
        const fallback = response.agents.find((agent) => agent.available)
        return fallback ? { ...current, agent_type: fallback.agent_type } : current
      })
    } catch {
      setAgents([{ agent_type: "mock-agent", available: true, executable: "mock-agent", reason: null }])
    }
  }, [])

  const startAgentRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsSubmittingAgentRun(true)
    setAgentSubmitStatus(null)
    try {
      const result = await apiRequest<AgentRunResponse>("/agent-runs", {
        method: "POST",
        body: JSON.stringify(agentForm),
      })
      await load()
      setSelectedRunId(result.run.id)
      setAgentSubmitStatus(`Run ${result.run.id} planned ${result.planned_command.join(" ")}.`)
    } catch (err) {
      setAgentSubmitStatus(err instanceof Error ? err.message : "Unable to start Agent Run")
    } finally {
      setIsSubmittingAgentRun(false)
    }
  }

  const executeDockerRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsSubmittingRun(true)
    setSubmitStatus(null)
    try {
      const result = await apiRequest<DockerExecuteResponse>("/docker/execute", {
        method: "POST",
        body: JSON.stringify({
          workspace: runForm.workspace,
          image: runForm.image,
          command: parseCommand(runForm.command),
          network_mode: runForm.network_mode,
          allow_host_callback: runForm.allow_host_callback,
          inject_proxy: runForm.inject_proxy,
          api_base_url: runForm.api_base_url,
        }),
      })
      await load()
      setSelectedRunId(result.run.id)
      setSubmitStatus(`Run ${result.run.id} completed with exit ${result.result.exit_code}.`)
    } catch (err) {
      setSubmitStatus(err instanceof Error ? err.message : "Unable to execute Docker run")
    } finally {
      setIsSubmittingRun(false)
    }
  }

  const cancelAgentRun = async (runId: string) => {
    try {
      await apiRequest<RunRecord>(`/agent-runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to cancel run")
    }
  }

  useEffect(() => {
    void load()
    void loadAgents()
  }, [load, loadAgents])

  useEffect(() => {
    if (!hasActiveRuns) return
    const interval = window.setInterval(() => void load(), 2000)
    return () => window.clearInterval(interval)
  }, [hasActiveRuns, load])

  useEffect(() => {
    if (!selectedRunId) {
      setEvents([])
      setCommands([])
      return
    }
    const encodedRunId = encodeURIComponent(selectedRunId)
    setEvents([])
    const loadCommands = () =>
      apiRequest<CommandRecord[]>(`/commands?run_id=${encodedRunId}`)
        .then(setCommands)
        .catch(() => setCommands([]))

    void loadCommands()
    void apiRequest<MicaEvent[]>(`/events?run_id=${encodedRunId}`)
      .then((history) => setEvents((current) => mergeEvents(current, history)))
      .catch(() => setEvents([]))

    if (selectedRunStatus !== "started") {
      return
    }

    const commandInterval = window.setInterval(() => void loadCommands(), 2000)
    const source = new EventSource(`${API_BASE_URL}/api/events/stream?run_id=${encodedRunId}`)
    const appendEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as MicaEvent
      setEvents((current) => mergeEvents(current, [event]))
      if (event.event_type === "run_completed" || event.event_type === "run_failed") {
        void load()
      }
    }
    eventTypes.forEach((type) => source.addEventListener(type, appendEvent))
    return () => {
      window.clearInterval(commandInterval)
      eventTypes.forEach((type) => source.removeEventListener(type, appendEvent))
      source.close()
    }
  }, [load, selectedRunId, selectedRunStatus])

  const outputEvents = events.filter((event) => event.event_type === "command_output")
  const commandOriginById = new Map(commands.map((command) => [command.id, command.command_origin]))
  const eventCommandOrigin = (event: MicaEvent) =>
    typeof event.payload.command_origin === "string"
      ? event.payload.command_origin
      : event.command_id
        ? commandOriginById.get(event.command_id)
        : undefined
  const visibleTraceEvents = events.filter(
    (event) => showRuntimeInternalTrace || eventCommandOrigin(event) !== "runtime_internal"
  )
  const hiddenRuntimeTraceCount = events.length - visibleTraceEvents.length
  const selectedAgent = agents.find((agent) => agent.agent_type === agentForm.agent_type)
  const canStartAgentRun = !isSubmittingAgentRun && Boolean(agentForm.prompt && agentForm.workspace && selectedAgent?.available)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Runs</h1>
        <p className="text-sm text-muted-foreground">
          Grouped command execution records for controlled Agent CLI sessions.
        </p>
      </div>

      {error && <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Start Agent Run</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={startAgentRun}>
            <label className="grid gap-1.5 text-sm font-medium">
              Task Prompt
              <Textarea
                name="prompt"
                className="min-h-24"
                value={agentForm.prompt}
                onChange={(event) => setAgentForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
              <label className="grid gap-1.5 text-sm font-medium">
                Workspace
                <Input
                  name="workspace"
                  value={agentForm.workspace}
                  onChange={(event) => setAgentForm((current) => ({ ...current, workspace: event.target.value }))}
                />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Agent
                <select
                  name="agent_type"
                  className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={agentForm.agent_type}
                  onChange={(event) =>
                    setAgentForm((current) => ({
                      ...current,
                      agent_type: event.target.value,
                    }))
                  }
                >
                  {agents.map((agent) => (
                    <option key={agent.agent_type} value={agent.agent_type} disabled={!agent.available}>
                      {agent.agent_type}
                      {agent.available ? "" : " unavailable"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Mode
                <select
                  name="runner_mode"
                  className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={agentForm.runner_mode}
                  onChange={(event) =>
                    setAgentForm((current) => ({
                      ...current,
                      runner_mode: event.target.value as AgentRunForm["runner_mode"],
                    }))
                  }
                >
                  <option value="local">local</option>
                  <option value="docker" disabled>
                    docker
                  </option>
                </select>
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={!canStartAgentRun}>
                {isSubmittingAgentRun ? "Starting..." : "Start Agent Run"}
              </Button>
              {agentSubmitStatus && <span className="text-sm text-muted-foreground">{agentSubmitStatus}</span>}
            </div>
            {selectedAgent && (
              <div className="rounded-lg border bg-muted p-3 text-xs text-muted-foreground">
                {selectedAgent.available ? (
                  <span>
                    {selectedAgent.agent_type} executable:{" "}
                    <code className="break-all">{selectedAgent.executable ?? "built-in"}</code>
                  </span>
                ) : (
                  <span>{selectedAgent.reason ?? `${selectedAgent.agent_type} is unavailable.`}</span>
                )}
              </div>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Advanced: Execute Docker Command</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={executeDockerRun}>
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
              <label className="grid gap-1.5 text-sm font-medium">
                Workspace
                <Input
                  name="workspace"
                  value={runForm.workspace}
                  onChange={(event) => setRunForm((current) => ({ ...current, workspace: event.target.value }))}
                />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Image
                <Input
                  name="image"
                  value={runForm.image}
                  onChange={(event) => setRunForm((current) => ({ ...current, image: event.target.value }))}
                />
              </label>
            </div>

            <label className="grid gap-1.5 text-sm font-medium">
              Command
              <Textarea
                name="command"
                className="min-h-20 font-mono text-xs"
                value={runForm.command}
                onChange={(event) => setRunForm((current) => ({ ...current, command: event.target.value }))}
              />
            </label>

            <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
              <label className="grid gap-1.5 text-sm font-medium">
                Network
                <select
                  name="network_mode"
                  className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={runForm.network_mode}
                  onChange={(event) =>
                    setRunForm((current) => ({
                      ...current,
                      network_mode: event.target.value as DockerRunForm["network_mode"],
                    }))
                  }
                >
                  <option value="none">none</option>
                  <option value="bridge">bridge</option>
                </select>
              </label>

              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex min-h-8 items-center gap-2 text-sm font-medium">
                  <input
                    name="inject_proxy"
                    type="checkbox"
                    checked={runForm.inject_proxy}
                    onChange={(event) =>
                      setRunForm((current) => ({ ...current, inject_proxy: event.target.checked }))
                    }
                  />
                  Inject proxy
                </label>
                <label className="flex min-h-8 items-center gap-2 text-sm font-medium">
                  <input
                    name="allow_host_callback"
                    type="checkbox"
                    checked={runForm.allow_host_callback}
                    onChange={(event) =>
                      setRunForm((current) => ({ ...current, allow_host_callback: event.target.checked }))
                    }
                  />
                  Allow host callback
                </label>
              </div>
            </div>

            {runForm.inject_proxy && (
              <label className="grid gap-1.5 text-sm font-medium">
                Container API URL
                <Input
                  name="api_base_url"
                  value={runForm.api_base_url}
                  onChange={(event) => setRunForm((current) => ({ ...current, api_base_url: event.target.value }))}
                />
              </label>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={isSubmittingRun}>
                {isSubmittingRun ? "Executing..." : "Execute"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setRunForm((current) => ({
                    ...current,
                    image: "mica-python-git:local",
                    command: "[\"git\",\"push\",\"origin\",\"main\"]",
                    network_mode: "bridge",
                    allow_host_callback: true,
                    inject_proxy: true,
                  }))
                }
              >
                Approval probe preset
              </Button>
              {submitStatus && <span className="text-sm text-muted-foreground">{submitStatus}</span>}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Commands</TableHead>
                  <TableHead>Approvals</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Failure</TableHead>
                  <TableHead>Trace</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => {
                  const summary = summaries[run.id]
                  return (
                    <TableRow key={run.id}>
                      <TableCell className="max-w-[300px] whitespace-normal">
                        <div className="font-medium">{run.source}</div>
                        <code className="mt-1 block break-words rounded bg-muted px-2 py-1 text-xs">{run.id}</code>
                        <div className="mt-1 text-xs text-muted-foreground">{run.cwd}</div>
                        <div className="mt-1 text-xs text-muted-foreground">Started {formatDate(run.started_at)}</div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={run.status} />
                      </TableCell>
                      <TableCell>
                        {summary ? (
                          <div className="space-y-1 text-sm">
                            <div>
                              {summary.agent_tool_commands} agent / {summary.runtime_internal_commands} runtime
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {summary.successful_commands}/{summary.total_commands} external binaries succeeded
                            </div>
                          </div>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>{summary?.approval_count ?? "-"}</TableCell>
                      <TableCell>{summary ? `${summary.risky_command_count} risky` : "-"}</TableCell>
                      <TableCell>{formatDuration(summary?.total_duration_ms)}</TableCell>
                      <TableCell className="max-w-[320px] whitespace-normal text-sm">
                        {summary?.failure_summary ? (
                          <div className="space-y-1">
                            <code className="block break-words rounded bg-muted px-2 py-1 text-xs">
                              {summary.failure_summary.failed_command}
                            </code>
                            <div className="text-xs text-muted-foreground">
                              exit {summary.failure_summary.exit_code ?? "-"} -{" "}
                              {summary.failure_summary.suggested_next_action}
                            </div>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant={selectedRunId === run.id ? "default" : "outline"}
                          onClick={() => setSelectedRunId(run.id)}
                        >
                          View
                        </Button>
                      </TableCell>
                      <TableCell>
                        {run.status === "started" ? (
                          <Button size="sm" variant="outline" onClick={() => void cancelAgentRun(run.id)}>
                            Cancel
                          </Button>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-sm text-muted-foreground">No runs yet.</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Run Evidence</CardTitle>
        </CardHeader>
        <CardContent>
          {selectedRunId && commands.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Layer</TableHead>
                  <TableHead>Command</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Approval</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {commands.map((command) => {
                  const selectedRun = runs.find((run) => run.id === selectedRunId)
                  const layer = command.requires_approval
                    ? "policy_gated"
                    : selectedRun?.source === "docker"
                      ? "docker-wrapper"
                      : command.command_origin
                  return (
                    <TableRow key={command.id}>
                      <TableCell>
                        <StatusBadge status={layer} />
                      </TableCell>
                      <TableCell className="max-w-[360px] whitespace-normal">
                        <code className="break-words rounded bg-muted px-2 py-1 text-xs">
                          {command.command_line}
                        </code>
                        {command.command_origin === "runtime_internal" && (
                          <div className="mt-1 text-xs text-muted-foreground">
                            Runtime housekeeping from the Agent CLI, not an explicit agent tool call.
                          </div>
                        )}
                        <div className="mt-1 text-xs text-muted-foreground">{command.cwd}</div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={command.status} />
                      </TableCell>
                      <TableCell>{command.risk_level}</TableCell>
                      <TableCell>{command.exit_code ?? "-"}</TableCell>
                      <TableCell>{formatDuration(command.duration_ms)}</TableCell>
                      <TableCell>
                        {command.approval_id ? (
                          <code className="rounded bg-muted px-2 py-1 text-xs">{command.approval_id}</code>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-sm text-muted-foreground">
              {selectedRunId ? "No command evidence for this run yet." : "Select a run to inspect command evidence."}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Realtime Logs</CardTitle>
        </CardHeader>
        <CardContent>
          {selectedRunId && outputEvents.length ? (
            <div className="max-h-[360px] overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100">
              {outputEvents.map((event) => {
                const stream = typeof event.payload.stream === "string" ? event.payload.stream : "stdout"
                const text =
                  typeof event.payload.text === "string" ? event.payload.text : JSON.stringify(event.payload)
                return (
                  <div
                    key={event.id}
                    className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 border-b border-zinc-800 py-1 last:border-b-0"
                  >
                    <span className={stream === "stderr" ? "text-red-300" : "text-emerald-300"}>{stream}</span>
                    <span className="min-w-0 whitespace-pre-wrap break-words">{text}</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="py-10 text-sm text-muted-foreground">
              {selectedRunId ? "No realtime log output for this run yet." : "Select a run to inspect realtime logs."}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Trace Events</CardTitle>
            {hiddenRuntimeTraceCount > 0 && (
              <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <input
                  type="checkbox"
                  checked={showRuntimeInternalTrace}
                  onChange={(event) => setShowRuntimeInternalTrace(event.target.checked)}
                />
                Show {hiddenRuntimeTraceCount} runtime internal events
              </label>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {selectedRunId && visibleTraceEvents.length ? (
            <div className="flex flex-col gap-3">
              {visibleTraceEvents.map((event) => (
                <div key={event.id} className="grid gap-2 border-b pb-3 last:border-b-0 md:grid-cols-[180px_1fr]">
                  <div>
                    <div className="font-mono text-xs text-muted-foreground">{formatDate(event.created_at)}</div>
                    <StatusBadge status={event.event_type} />
                    {eventCommandOrigin(event) && (
                      <div className="mt-1">
                        <StatusBadge status={eventCommandOrigin(event) ?? "external_binary"} />
                      </div>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{event.message}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      {event.command_id && <span>command {event.command_id}</span>}
                      {event.approval_id && <span>approval {event.approval_id}</span>}
                    </div>
                    <pre className="mt-2 whitespace-pre-wrap break-words rounded bg-muted p-2 text-xs">
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-10 text-sm text-muted-foreground">
              {selectedRunId ? "No trace events for this run yet." : "Select a run to inspect trace events."}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
