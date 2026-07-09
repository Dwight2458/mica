"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { type FormEvent, useCallback, useEffect, useState } from "react"
import { EyeIcon, PlayIcon } from "lucide-react"

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
  type AgentAvailability,
  type AgentListResponse,
  type AgentSession,
  type SessionContinueResponse,
} from "@/lib/api"
import { cn } from "@/lib/utils"

type SessionForm = {
  prompt: string
  workspace: string
  agent_type: string
  runner_mode: "local" | "docker"
}

const defaultForm: SessionForm = {
  prompt: "写一个贪吃蛇小游戏",
  workspace: "C:\\Users\\24582\\Downloads\\testrepo",
  agent_type: "mock-agent",
  runner_mode: "local",
}

export default function SessionsPage() {
  const router = useRouter()
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [agents, setAgents] = useState<AgentAvailability[]>([
    { agent_type: "mock-agent", available: true, executable: "mock-agent", reason: null },
  ])
  const [form, setForm] = useState<SessionForm>(defaultForm)
  const [error, setError] = useState<string | null>(null)
  const [submitStatus, setSubmitStatus] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const load = useCallback(async () => {
    try {
      const nextSessions = await apiRequest<AgentSession[]>("/sessions")
      setSessions(nextSessions)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load sessions")
    }
  }, [])

  const loadAgents = useCallback(async () => {
    try {
      const response = await apiRequest<AgentListResponse>("/agent-runs/agents")
      setAgents(response.agents)
      setForm((current) => {
        const selected = response.agents.find((agent) => agent.agent_type === current.agent_type)
        if (selected?.available) return current
        const fallback = response.agents.find((agent) => agent.available)
        return fallback ? { ...current, agent_type: fallback.agent_type } : current
      })
    } catch {
      setAgents([{ agent_type: "mock-agent", available: true, executable: "mock-agent", reason: null }])
    }
  }, [])

  useEffect(() => {
    void load()
    void loadAgents()
  }, [load, loadAgents])

  const createSession = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsSubmitting(true)
    setSubmitStatus(null)
    try {
      const result = await apiRequest<SessionContinueResponse>("/sessions", {
        method: "POST",
        body: JSON.stringify(form),
      })
      router.push(`/sessions/${encodeURIComponent(result.session.id)}`)
    } catch (err) {
      setSubmitStatus(err instanceof Error ? err.message : "Unable to create session")
    } finally {
      setIsSubmitting(false)
    }
  }

  const selectedAgent = agents.find((agent) => agent.agent_type === form.agent_type)
  const canStart = !isSubmitting && Boolean(form.prompt && form.workspace && selectedAgent?.available)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Sessions</h1>
        <p className="text-sm text-muted-foreground">Persistent agent goals with governed runs underneath.</p>
      </div>

      {error && <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Start Agent Session</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={createSession}>
            <label className="grid gap-1.5 text-sm font-medium">
              Goal
              <Textarea
                name="prompt"
                className="min-h-24"
                value={form.prompt}
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
              <label className="grid gap-1.5 text-sm font-medium">
                Workspace
                <Input
                  name="workspace"
                  value={form.workspace}
                  onChange={(event) => setForm((current) => ({ ...current, workspace: event.target.value }))}
                />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Agent
                <select
                  name="agent_type"
                  className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={form.agent_type}
                  onChange={(event) => setForm((current) => ({ ...current, agent_type: event.target.value }))}
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
                  value={form.runner_mode}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, runner_mode: event.target.value as SessionForm["runner_mode"] }))
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
              <Button type="submit" disabled={!canStart}>
                <PlayIcon data-icon="inline-start" />
                {isSubmitting ? "Starting..." : "Start Session"}
              </Button>
              {submitStatus && <span className="text-sm text-muted-foreground">{submitStatus}</span>}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Sessions</CardTitle>
        </CardHeader>
        <CardContent>
          {sessions.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Session</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Workspace</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => (
                  <TableRow key={session.id}>
                    <TableCell>
                      <StatusBadge status={session.status} />
                    </TableCell>
                    <TableCell className="max-w-[360px] whitespace-normal">
                      <div className="font-medium">{session.title}</div>
                      <code className="mt-1 block truncate rounded bg-muted px-2 py-1 text-xs">{session.id}</code>
                    </TableCell>
                    <TableCell>{session.agent_type}</TableCell>
                    <TableCell className="max-w-[360px] whitespace-normal">
                      <span className="break-words text-sm">{session.workspace}</span>
                    </TableCell>
                    <TableCell>{formatDate(session.updated_at)}</TableCell>
                    <TableCell>
                      <Link
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                        href={`/sessions/${encodeURIComponent(session.id)}`}
                      >
                        <EyeIcon data-icon="inline-start" />
                        Open
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-sm text-muted-foreground">No sessions yet.</div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

