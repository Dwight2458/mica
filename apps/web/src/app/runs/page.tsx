"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { type FormEvent, useCallback, useEffect, useState } from "react"
import { EyeIcon, PlayIcon, SquareIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Button, buttonVariants } from "@/components/ui/button"
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
  apiRequest,
  formatDate,
  formatDuration,
  type AgentAvailability,
  type AgentListResponse,
  type AgentRunResponse,
  type DockerExecuteResponse,
  type RunRecord,
  type RunSummary,
} from "@/lib/api"
import { cn } from "@/lib/utils"

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
  const router = useRouter()
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({})
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
  const hasActiveRuns = runs.some((run) => run.status === "started")

  const load = useCallback(async () => {
    try {
      const nextRuns = await apiRequest<RunRecord[]>("/runs")
      const nextSummaries = await Promise.all(
        nextRuns.map((run) => apiRequest<RunSummary>(`/runs/${run.id}/summary`))
      )
      setRuns(nextRuns)
      setSummaries(Object.fromEntries(nextSummaries.map((summary) => [summary.run_id, summary])))
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
      setAgentSubmitStatus(`Run ${result.run.id} started.`)
      router.push(`/runs/${encodeURIComponent(result.run.id)}`)
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
      setSubmitStatus(`Run ${result.run.id} completed with exit ${result.result.exit_code}.`)
      router.push(`/runs/${encodeURIComponent(result.run.id)}`)
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

  const selectedAgent = agents.find((agent) => agent.agent_type === agentForm.agent_type)
  const canStartAgentRun =
    !isSubmittingAgentRun && Boolean(agentForm.prompt && agentForm.workspace && selectedAgent?.available)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Runs</h1>
        <p className="text-sm text-muted-foreground">Start agent sessions and open their execution evidence.</p>
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
                <PlayIcon data-icon="inline-start" />
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

      <details className="rounded-lg border bg-card p-4 text-card-foreground">
        <summary className="cursor-pointer text-sm font-medium">Advanced Docker command</summary>
        <form className="mt-4 grid gap-4" onSubmit={executeDockerRun}>
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
                  onChange={(event) => setRunForm((current) => ({ ...current, inject_proxy: event.target.checked }))}
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
              <PlayIcon data-icon="inline-start" />
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
      </details>

      <Card>
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Workspace</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Governed</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => {
                  const summary = summaries[run.id]
                  return (
                    <TableRow key={run.id}>
                      <TableCell>
                        <StatusBadge status={run.status} />
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{run.source}</div>
                        <code className="mt-1 block max-w-[220px] truncate rounded bg-muted px-2 py-1 text-xs">
                          {run.id}
                        </code>
                      </TableCell>
                      <TableCell className="max-w-[360px] whitespace-normal">
                        <div className="break-words text-sm">{run.cwd}</div>
                      </TableCell>
                      <TableCell>{formatDuration(summary?.total_duration_ms)}</TableCell>
                      <TableCell>
                        {summary ? (
                          <div className="space-y-1 text-sm">
                            <div>
                              {summary.successful_governed_commands}/{summary.governed_commands} succeeded
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {summary.approval_count} approvals, {summary.risky_command_count} risky
                            </div>
                          </div>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>{formatDate(run.started_at)}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <Link
                            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                            href={`/runs/${encodeURIComponent(run.id)}`}
                          >
                            <EyeIcon data-icon="inline-start" />
                            View
                          </Link>
                          {run.status === "started" && (
                            <Button size="sm" variant="outline" onClick={() => void cancelAgentRun(run.id)}>
                              <SquareIcon data-icon="inline-start" />
                              Cancel
                            </Button>
                          )}
                        </div>
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
    </div>
  )
}

