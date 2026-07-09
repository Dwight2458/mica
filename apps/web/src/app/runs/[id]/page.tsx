"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useState } from "react"
import { ArrowLeftIcon, CheckIcon, SquareIcon, XIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  API_BASE_URL,
  apiRequest,
  formatDate,
  formatDuration,
  type Approval,
  type ApprovalStatus,
  type CommandRecord,
  type MicaEvent,
  type RunRecord,
  type RunSummary,
} from "@/lib/api"
import {
  agentOutputText,
  eventPayloadString,
  isLowSignalAgentEvent,
  mergeEvents,
  runEventTypes,
  runPromptFromEvents,
} from "@/lib/run-utils"
import { cn } from "@/lib/utils"

type SourceFilter = "all" | "agent_tool" | "external_binary" | "runtime_internal"
type StatusFilter = "all" | CommandRecord["status"]

export default function RunDetailPage() {
  const params = useParams<{ id: string }>()
  const runId = params.id
  const [run, setRun] = useState<RunRecord | null>(null)
  const [summary, setSummary] = useState<RunSummary | null>(null)
  const [events, setEvents] = useState<MicaEvent[]>([])
  const [commands, setCommands] = useState<CommandRecord[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showRuntimeInternal, setShowRuntimeInternal] = useState(false)
  const [showDebugEvents, setShowDebugEvents] = useState(false)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all")
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [decisionStatus, setDecisionStatus] = useState<string | null>(null)

  const loadRun = useCallback(async () => {
    const encodedRunId = encodeURIComponent(runId)
    const [nextRun, nextSummary] = await Promise.all([
      apiRequest<RunRecord>(`/runs/${encodedRunId}`),
      apiRequest<RunSummary>(`/runs/${encodedRunId}/summary`),
    ])
    setRun(nextRun)
    setSummary(nextSummary)
  }, [runId])

  const loadEvidence = useCallback(async () => {
    const encodedRunId = encodeURIComponent(runId)
    const [nextEvents, nextCommands, nextApprovals] = await Promise.all([
      apiRequest<MicaEvent[]>(`/events?run_id=${encodedRunId}`),
      apiRequest<CommandRecord[]>(`/commands?run_id=${encodedRunId}`),
      apiRequest<Approval[]>("/approvals"),
    ])
    setEvents((current) => mergeEvents(current, nextEvents))
    setCommands(nextCommands)
    setApprovals(nextApprovals)
  }, [runId])

  const refresh = useCallback(async () => {
    try {
      await Promise.all([loadRun(), loadEvidence()])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load run")
    }
  }, [loadEvidence, loadRun])

  useEffect(() => {
    setRun(null)
    setSummary(null)
    setEvents([])
    setCommands([])
    setApprovals([])
    void refresh()
  }, [refresh, runId])

  useEffect(() => {
    if (run?.status !== "started") return
    const encodedRunId = encodeURIComponent(runId)
    const poll = window.setInterval(() => void refresh(), 2000)
    const source = new EventSource(`${API_BASE_URL}/api/events/stream?run_id=${encodedRunId}`)
    const appendEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as MicaEvent
      setEvents((current) => mergeEvents(current, [event]))
      if (event.event_type === "run_completed" || event.event_type === "run_failed") {
        void refresh()
      }
    }
    runEventTypes.forEach((type) => source.addEventListener(type, appendEvent))
    return () => {
      window.clearInterval(poll)
      runEventTypes.forEach((type) => source.removeEventListener(type, appendEvent))
      source.close()
    }
  }, [refresh, run?.status, runId])

  const commandOriginById = useMemo(() => new Map(commands.map((command) => [command.id, command.command_origin])), [commands])
  const eventCommandOrigin = useCallback(
    (event: MicaEvent) =>
      typeof event.payload.command_origin === "string"
        ? event.payload.command_origin
        : event.command_id
          ? commandOriginById.get(event.command_id)
          : undefined,
    [commandOriginById]
  )

  const approvalIds = useMemo(() => {
    const ids = new Set<string>()
    commands.forEach((command) => {
      if (command.approval_id) ids.add(command.approval_id)
    })
    events.forEach((event) => {
      if (event.approval_id) ids.add(event.approval_id)
    })
    return ids
  }, [commands, events])

  const runApprovals = approvals.filter((approval) => approvalIds.has(approval.id))
  const pendingApprovals = runApprovals.filter((approval) => approval.status === "pending")
  const fileChangeEvents = events.filter((event) => event.event_type === "file_changed")
  const outputEvents = events.filter((event) => agentOutputText(event) !== null)
  const visibleCommands = commands.filter((command) => {
    if (!showRuntimeInternal && command.command_origin === "runtime_internal") return false
    if (sourceFilter !== "all" && command.command_origin !== sourceFilter) return false
    if (statusFilter !== "all" && command.status !== statusFilter) return false
    return true
  })
  const hiddenRuntimeCommandCount = commands.filter((command) => command.command_origin === "runtime_internal").length
  const visibleTraceEvents = events.filter(
    (event) =>
      (showRuntimeInternal || eventCommandOrigin(event) !== "runtime_internal") &&
      (showDebugEvents || !isLowSignalAgentEvent(event))
  )
  const hiddenTraceCount = events.length - visibleTraceEvents.length
  const prompt = runPromptFromEvents(events)
  const failure = summary?.failure_summary

  const cancelRun = async () => {
    if (!run) return
    try {
      await apiRequest<RunRecord>(`/agent-runs/${encodeURIComponent(run.id)}/cancel`, { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to cancel run")
    }
  }

  const decideApproval = async (approvalId: string, decision: Exclude<ApprovalStatus, "pending">) => {
    setDecisionStatus(null)
    try {
      await apiRequest<Approval>(`/approvals/${encodeURIComponent(approvalId)}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision, resolved_by: "local-user" }),
      })
      setDecisionStatus(`Approval ${decision}.`)
      await refresh()
    } catch (err) {
      setDecisionStatus(err instanceof Error ? err.message : "Unable to decide approval")
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }))} href="/runs">
          <ArrowLeftIcon data-icon="inline-start" />
          Runs
        </Link>
        {run?.status === "started" && (
          <Button size="sm" variant="outline" onClick={() => void cancelRun()}>
            <SquareIcon data-icon="inline-start" />
            Cancel
          </Button>
        )}
      </div>

      {error && <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">{error}</p>}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {run && <StatusBadge status={run.status} />}
                <StatusBadge status={run?.source ?? "run"} />
              </div>
              <CardTitle className="break-words text-xl">{prompt ?? "Agent run"}</CardTitle>
              <div className="mt-2 break-all font-mono text-xs text-muted-foreground">{runId}</div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <Metric label="Duration" value={formatDuration(summary?.total_duration_ms)} />
              <Metric
                label="Governed"
                value={
                  summary
                    ? `${summary.successful_governed_commands}/${summary.governed_commands}`
                    : "-"
                }
              />
              <Metric label="Approvals" value={String(summary?.approval_count ?? "-")} />
              <Metric label="Risky" value={String(summary?.risky_command_count ?? "-")} />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-[120px_1fr]">
            <span>Workspace</span>
            <code className="break-all rounded bg-muted px-2 py-1 text-xs">{run?.cwd ?? "-"}</code>
            <span>Started</span>
            <span>{formatDate(run?.started_at ?? null)}</span>
            <span>Finished</span>
            <span>{formatDate(run?.finished_at ?? null)}</span>
          </div>
        </CardContent>
      </Card>

      {pendingApprovals.length > 0 && (
        <Card className="border-yellow-300 bg-yellow-50/60 dark:border-yellow-900 dark:bg-yellow-950/20">
          <CardHeader>
            <CardTitle>Pending Approval</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {pendingApprovals.map((approval) => (
              <div key={approval.id} className="grid gap-3 rounded-md border bg-background p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={approval.risk_level} />
                  <StatusBadge status={approval.status} />
                  <code className="break-all text-xs">{approval.id}</code>
                </div>
                <code className="break-words rounded bg-muted px-2 py-1 text-xs">{approval.command_line}</code>
                <p className="text-sm text-muted-foreground">{approval.reason}</p>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => void decideApproval(approval.id, "approved")}>
                    <CheckIcon data-icon="inline-start" />
                    Approve
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => void decideApproval(approval.id, "rejected")}>
                    <XIcon data-icon="inline-start" />
                    Reject
                  </Button>
                </div>
              </div>
            ))}
            {decisionStatus && <p className="text-sm text-muted-foreground">{decisionStatus}</p>}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
          <TabsTrigger value="trace">Trace</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Run Summary</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="Total commands" value={String(summary?.total_commands ?? "-")} />
                <Metric label="Agent tools" value={String(summary?.agent_tool_commands ?? "-")} />
                <Metric label="Runtime internal" value={String(summary?.runtime_internal_commands ?? "-")} />
                <Metric label="Files changed" value={String(fileChangeEvents.length)} />
              </div>
              {failure ? (
                <div className="grid gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950/20">
                  <div className="font-medium">Failure summary</div>
                  <code className="break-words rounded bg-background px-2 py-1 text-xs">{failure.failed_command}</code>
                  <div className="text-muted-foreground">Exit {failure.exit_code ?? "-"} - {failure.reason}</div>
                  <div>{failure.suggested_next_action}</div>
                </div>
              ) : (
                <div className="rounded-md border bg-muted p-3 text-sm text-muted-foreground">
                  {run?.status === "completed"
                    ? "Run completed without a failure summary."
                    : "Run summary will update as the agent produces evidence."}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="evidence">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle>Run Evidence</CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    value={sourceFilter}
                    onChange={(event) => setSourceFilter(event.target.value as SourceFilter)}
                  >
                    <option value="all">all sources</option>
                    <option value="agent_tool">agent tool</option>
                    <option value="external_binary">external binary</option>
                    <option value="runtime_internal">runtime internal</option>
                  </select>
                  <select
                    className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                  >
                    <option value="all">all status</option>
                    <option value="started">started</option>
                    <option value="waiting_approval">waiting approval</option>
                    <option value="completed">completed</option>
                    <option value="failed">failed</option>
                    <option value="rejected">rejected</option>
                    <option value="timeout">timeout</option>
                  </select>
                  {hiddenRuntimeCommandCount > 0 && (
                    <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={showRuntimeInternal}
                        onChange={(event) => setShowRuntimeInternal(event.target.checked)}
                      />
                      Runtime internal
                    </label>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="grid gap-5">
              {visibleCommands.length ? (
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
                    {visibleCommands.map((command) => {
                      const layer = command.requires_approval ? "policy_gated" : command.command_origin
                      return (
                        <TableRow key={command.id}>
                          <TableCell>
                            <StatusBadge status={layer} />
                          </TableCell>
                          <TableCell className="max-w-[420px] whitespace-normal">
                            <code className="break-words rounded bg-muted px-2 py-1 text-xs">
                              {command.command_line}
                            </code>
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
                <EmptyState
                  text={
                    hiddenRuntimeCommandCount
                      ? "No user-facing command evidence matches the current filters."
                      : "No command evidence for this run yet."
                  }
                />
              )}

              <section className="grid gap-3">
                <h3 className="text-sm font-medium">Approvals</h3>
                {runApprovals.length ? (
                  <div className="grid gap-2">
                    {runApprovals.map((approval) => (
                      <div key={approval.id} className="grid gap-2 rounded-md border p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={approval.status} />
                          <StatusBadge status={approval.risk_level} />
                          <code className="break-all text-xs">{approval.id}</code>
                        </div>
                        <code className="break-words rounded bg-muted px-2 py-1 text-xs">{approval.command_line}</code>
                        <div className="text-muted-foreground">{approval.reason}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState text="No approvals are linked to this run." />
                )}
              </section>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <CardTitle>Realtime Logs</CardTitle>
            </CardHeader>
            <CardContent>
              {outputEvents.length ? (
                <div className="max-h-[520px] overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100">
                  {outputEvents.map((event) => {
                    const stream = eventPayloadString(event, "stream") ?? "stdout"
                    const text = agentOutputText(event) ?? ""
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
                <EmptyState text="No realtime log output for this run yet." />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="trace">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle>Trace Events</CardTitle>
                <div className="flex flex-wrap items-center gap-3">
                  {hiddenTraceCount > 0 && (
                    <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={showRuntimeInternal}
                        onChange={(event) => setShowRuntimeInternal(event.target.checked)}
                      />
                      Show hidden internal
                    </label>
                  )}
                  {events.some(isLowSignalAgentEvent) && (
                    <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={showDebugEvents}
                        onChange={(event) => setShowDebugEvents(event.target.checked)}
                      />
                      Debug events
                    </label>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {visibleTraceEvents.length ? (
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
                          {typeof event.payload.exit_code === "number" && <span>exit {event.payload.exit_code}</span>}
                          {typeof event.payload.duration_ms === "number" && (
                            <span>{formatDuration(event.payload.duration_ms)}</span>
                          )}
                        </div>
                        <details className="mt-2 rounded bg-muted p-2">
                          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Payload</summary>
                          <pre className="mt-2 whitespace-pre-wrap break-words text-xs">
                            {JSON.stringify(event.payload, null, 2)}
                          </pre>
                        </details>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState text="No trace events for this run yet." />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border bg-muted/40 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold">{value}</div>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed py-10 text-center text-sm text-muted-foreground">{text}</div>
}

