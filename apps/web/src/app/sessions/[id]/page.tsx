"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { type FormEvent, useCallback, useEffect, useState } from "react"
import { ArrowLeftIcon, ExternalLinkIcon, SendIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import {
  apiRequest,
  formatDate,
  formatDuration,
  type AgentSession,
  type RunRecord,
  type RunSummary,
  type SessionContinueResponse,
  type SessionMessage,
} from "@/lib/api"
import { cn } from "@/lib/utils"

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>()
  const sessionId = params.id
  const [session, setSession] = useState<AgentSession | null>(null)
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [latestRun, setLatestRun] = useState<RunRecord | null>(null)
  const [latestSummary, setLatestSummary] = useState<RunSummary | null>(null)
  const [message, setMessage] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitStatus, setSubmitStatus] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const load = useCallback(async () => {
    try {
      const encoded = encodeURIComponent(sessionId)
      const [nextSession, nextMessages] = await Promise.all([
        apiRequest<AgentSession>(`/sessions/${encoded}`),
        apiRequest<SessionMessage[]>(`/sessions/${encoded}/messages`),
      ])
      setSession(nextSession)
      setMessages(nextMessages)
      if (nextSession.last_run_id) {
        const encodedRunId = encodeURIComponent(nextSession.last_run_id)
        const [run, summary] = await Promise.all([
          apiRequest<RunRecord>(`/runs/${encodedRunId}`),
          apiRequest<RunSummary>(`/runs/${encodedRunId}/summary`),
        ])
        setLatestRun(run)
        setLatestSummary(summary)
      } else {
        setLatestRun(null)
        setLatestSummary(null)
      }
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load session")
    }
  }, [sessionId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (session?.status !== "active") return
    const interval = window.setInterval(() => void load(), 2000)
    return () => window.clearInterval(interval)
  }, [load, session?.status])

  const continueSession = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!message.trim()) return
    setIsSubmitting(true)
    setSubmitStatus(null)
    try {
      const result = await apiRequest<SessionContinueResponse>(`/sessions/${encodeURIComponent(sessionId)}/continue`, {
        method: "POST",
        body: JSON.stringify({ message }),
      })
      setSession(result.session)
      setMessage("")
      await load()
    } catch (err) {
      setSubmitStatus(err instanceof Error ? err.message : "Unable to continue session")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }))} href="/sessions">
          <ArrowLeftIcon data-icon="inline-start" />
          Sessions
        </Link>
        {session?.last_run_id && (
          <Link
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            href={`/runs/${encodeURIComponent(session.last_run_id)}`}
          >
            <ExternalLinkIcon data-icon="inline-start" />
            Latest Run
          </Link>
        )}
      </div>

      {error && <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">{error}</p>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="grid min-w-0 gap-4">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap gap-2">
                    {session && <StatusBadge status={session.status} />}
                    {session && <StatusBadge status={session.agent_type} />}
                  </div>
                  <CardTitle className="break-words text-xl">{session?.title ?? "Agent session"}</CardTitle>
                  <div className="mt-2 break-all font-mono text-xs text-muted-foreground">{sessionId}</div>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-[120px_1fr]">
                <span>Workspace</span>
                <code className="break-all rounded bg-muted px-2 py-1 text-xs">{session?.workspace ?? "-"}</code>
                <span>Updated</span>
                <span>{formatDate(session?.updated_at ?? null)}</span>
                <span>Native Session</span>
                <code className="break-all rounded bg-muted px-2 py-1 text-xs">
                  {session?.external_session_id ?? "not captured yet"}
                </code>
                <span>Transport</span>
                <span>{session?.transport ?? "process"}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Conversation</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid max-h-[560px] gap-3 overflow-auto pr-1">
                {messages.length ? (
                  messages.map((item) => (
                    <div
                      key={item.id}
                      className={cn(
                        "max-w-[88%] rounded-lg border p-3 text-sm",
                        item.role === "user"
                          ? "ml-auto bg-primary text-primary-foreground"
                          : "mr-auto bg-muted text-foreground"
                      )}
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs opacity-75">
                        <span>{item.role}</span>
                        <span>{formatDate(item.created_at)}</span>
                        {item.run_id && (
                          <Link className="underline-offset-4 hover:underline" href={`/runs/${item.run_id}`}>
                            run
                          </Link>
                        )}
                      </div>
                      <div className="whitespace-pre-wrap break-words">{item.content}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-md border border-dashed py-10 text-center text-sm text-muted-foreground">
                    No messages yet.
                  </div>
                )}
              </div>

              <form className="grid gap-3 border-t pt-4" onSubmit={continueSession}>
                <Textarea
                  className="min-h-24"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Add details, approve an approach, or redirect the agent..."
                />
                <div className="flex flex-wrap items-center gap-3">
                  <Button type="submit" disabled={isSubmitting || !message.trim()}>
                    <SendIcon data-icon="inline-start" />
                    {isSubmitting ? "Sending..." : "Continue Session"}
                  </Button>
                  {submitStatus && <span className="text-sm text-muted-foreground">{submitStatus}</span>}
                </div>
              </form>
            </CardContent>
          </Card>
        </section>

        <aside className="grid h-fit gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Latest Run</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              {latestRun ? (
                <>
                  <div className="flex flex-wrap gap-2">
                    <StatusBadge status={latestRun.status} />
                    <StatusBadge status={latestRun.source} />
                  </div>
                  <code className="break-all rounded bg-muted px-2 py-1 text-xs">{latestRun.id}</code>
                  <div className="grid grid-cols-2 gap-2">
                    <Metric label="Duration" value={formatDuration(latestSummary?.total_duration_ms)} />
                    <Metric label="Governed" value={`${latestSummary?.successful_governed_commands ?? "-"}/${latestSummary?.governed_commands ?? "-"}`} />
                    <Metric label="Approvals" value={String(latestSummary?.approval_count ?? "-")} />
                    <Metric label="Risky" value={String(latestSummary?.risky_command_count ?? "-")} />
                  </div>
                  <Link
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit")}
                    href={`/runs/${encodeURIComponent(latestRun.id)}`}
                  >
                    <ExternalLinkIcon data-icon="inline-start" />
                    Open Evidence
                  </Link>
                </>
              ) : (
                <div className="rounded-md border border-dashed py-8 text-center text-sm text-muted-foreground">
                  No run yet.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Session Boundary</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm text-muted-foreground">
              <p>Session keeps the goal, display messages, and native agent handle.</p>
              <p>Run keeps one Agent CLI invocation and its governance evidence.</p>
              <p>Continuation uses the agent's native session/thread id when available.</p>
              <p>Command records remain the governance layer.</p>
            </CardContent>
          </Card>
        </aside>
      </div>
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
