"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react"
import { ArrowLeftIcon, CheckIcon, ExternalLinkIcon, SendIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { SessionMessageView } from "@/components/session-message"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import {
  apiRequest,
  API_BASE_URL,
  formatDate,
  formatDuration,
  type AgentSession,
  type RunRecord,
  type RunSummary,
  type SessionContinueResponse,
  type SessionInteraction,
  type SessionInteractionRespondResponse,
  type SessionMessage,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  buildNativeAnswers,
  groupNativeQuestionOptions,
  hasCompleteNativeAnswers,
  toggleNativeAnswer,
} from "@/lib/interaction-utils"

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>()
  const sessionId = params.id
  const [session, setSession] = useState<AgentSession | null>(null)
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [interactions, setInteractions] = useState<SessionInteraction[]>([])
  const [latestRun, setLatestRun] = useState<RunRecord | null>(null)
  const [latestSummary, setLatestSummary] = useState<RunSummary | null>(null)
  const [message, setMessage] = useState("")
  const [interactionInputs, setInteractionInputs] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitStatus, setSubmitStatus] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const load = useCallback(async () => {
    try {
      const encoded = encodeURIComponent(sessionId)
      const [nextSession, nextMessages, nextInteractions] = await Promise.all([
        apiRequest<AgentSession>(`/sessions/${encoded}`),
        apiRequest<SessionMessage[]>(`/sessions/${encoded}/messages`),
        apiRequest<SessionInteraction[]>(`/sessions/${encoded}/interactions?status=pending`),
      ])
      setSession(nextSession)
      setMessages(nextMessages)
      setInteractions(nextInteractions)
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
    if (session?.status !== "active" && session?.status !== "waiting_user_input") return
    const interval = window.setInterval(() => void load(), 5000)
    if (!session.last_run_id) return () => window.clearInterval(interval)

    const source = new EventSource(
      `${API_BASE_URL}/api/events/stream?run_id=${encodeURIComponent(session.last_run_id)}`
    )
    let refreshTimer: number | null = null
    const refreshFromEvent = () => {
      if (refreshTimer !== null) window.clearTimeout(refreshTimer)
      refreshTimer = window.setTimeout(() => void load(), 50)
    }
    const eventTypes = [
      "interaction_required",
      "interaction_responded",
      "interaction_dismissed",
      "command_output",
      "run_completed",
      "run_failed",
    ]
    eventTypes.forEach((type) => source.addEventListener(type, refreshFromEvent))
    return () => {
      window.clearInterval(interval)
      if (refreshTimer !== null) window.clearTimeout(refreshTimer)
      eventTypes.forEach((type) => source.removeEventListener(type, refreshFromEvent))
      source.close()
    }
  }, [load, session?.last_run_id, session?.status])

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

  const respondInteraction = async (
    interaction: SessionInteraction,
    response: string,
    options?: { optionId?: string; answers?: string[][]; remember?: boolean }
  ) => {
    setIsSubmitting(true)
    setSubmitStatus(null)
    try {
      await apiRequest<SessionInteractionRespondResponse>(
        `/session-interactions/${encodeURIComponent(interaction.id)}/respond`,
        {
          method: "POST",
          body: JSON.stringify({
            response,
            option_id: options?.optionId ?? null,
            answers: options?.answers ?? null,
            remember: options?.remember ?? false,
          }),
        }
      )
      setInteractionInputs((current) => ({ ...current, [interaction.id]: "" }))
      await load()
    } catch (err) {
      setSubmitStatus(err instanceof Error ? err.message : "Unable to respond")
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
              {interactions.length ? (
                <div className="grid gap-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-900 dark:bg-yellow-950/30">
                  <div>
                    <h3 className="font-medium">Needs Your Input</h3>
                    <p className="text-sm text-muted-foreground">
                      Respond here instead of hunting through the transcript.
                    </p>
                  </div>
                  {interactions.map((interaction) => (
                    <InteractionCard
                      key={interaction.id}
                      interaction={interaction}
                      value={interactionInputs[interaction.id] ?? ""}
                      disabled={isSubmitting}
                      onChange={(value) =>
                        setInteractionInputs((current) => ({ ...current, [interaction.id]: value }))
                      }
                      onRespond={(response, options) => void respondInteraction(interaction, response, options)}
                    />
                  ))}
                </div>
              ) : null}

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
                      <SessionMessageView message={item} />
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
              <p>Continuation uses the agent&apos;s native session/thread id when available.</p>
              <p>Command records remain the governance layer.</p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  )
}

function InteractionCard({
  interaction,
  value,
  disabled,
  onChange,
  onRespond,
}: {
  interaction: SessionInteraction
  value: string
  disabled: boolean
  onChange: (value: string) => void
  onRespond: (response: string, options?: { optionId?: string; answers?: string[][]; remember?: boolean }) => void
}) {
  const [nativeAnswers, setNativeAnswers] = useState<Record<number, string[]>>({})
  const sourceLabel =
    interaction.source === "heuristic"
      ? "detected"
      : interaction.source === "structured"
        ? "structured"
        : "native"
  const questionGroups = useMemo(() => groupNativeQuestionOptions(interaction.options), [interaction.options])
  const requiresNativeSubmit =
    interaction.source === "native" &&
    questionGroups.length > 0 &&
    (questionGroups.length > 1 || questionGroups.some((group) => group.multiple))

  return (
    <div className="grid gap-3 rounded-md border bg-background p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={interaction.kind} />
        <StatusBadge status={sourceLabel} />
        {interaction.external_id && <code className="break-all text-xs text-muted-foreground">{interaction.external_id}</code>}
      </div>
      {!requiresNativeSubmit && <div className="whitespace-pre-wrap text-sm">{interaction.prompt}</div>}

      {interaction.kind === "choice" && requiresNativeSubmit ? (
        <div className="grid gap-4">
          {questionGroups.map((group) => (
            <section key={group.index} className="grid gap-2 border-t pt-3 first:border-t-0 first:pt-0">
              {group.header && <div className="text-xs font-medium text-muted-foreground">{group.header}</div>}
              <div className="text-sm font-medium">{group.question}</div>
              <div className="text-xs text-muted-foreground">
                {group.multiple ? "Select one or more" : "Select one"}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {group.options.map((option) => {
                  const optionValue = option.value || option.label
                  const selected = nativeAnswers[group.index]?.includes(optionValue) ?? false
                  return (
                    <Button
                      key={option.id}
                      type="button"
                      className="h-auto min-h-10 justify-start whitespace-normal text-left"
                      size="sm"
                      variant={selected ? "default" : "outline"}
                      disabled={disabled}
                      aria-pressed={selected}
                      onClick={() =>
                        setNativeAnswers((current) =>
                          toggleNativeAnswer(current, group.index, optionValue, group.multiple),
                        )
                      }
                    >
                      {selected && <CheckIcon data-icon="inline-start" />}
                      <span className="grid gap-0.5">
                        <span>{option.label}</span>
                        {option.description && (
                          <span className={selected ? "text-primary-foreground/80" : "text-muted-foreground"}>
                            {option.description}
                          </span>
                        )}
                      </span>
                    </Button>
                  )
                })}
              </div>
            </section>
          ))}
          <Button
            type="button"
            className="w-fit"
            disabled={disabled || !hasCompleteNativeAnswers(questionGroups, nativeAnswers)}
            onClick={() => {
              const answers = buildNativeAnswers(questionGroups, nativeAnswers)
              onRespond(answers.map((answer) => answer.join(", ")).join("; "), { answers })
            }}
          >
            <SendIcon data-icon="inline-start" />
            Submit Answers
          </Button>
        </div>
      ) : interaction.kind === "choice" && interaction.options.length ? (
        <div className="flex flex-wrap gap-2">
          {interaction.options.map((option, index) => (
            <Button
              key={option.id}
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() => onRespond(option.value || option.label, { optionId: option.id })}
            >
              {index + 1}. {option.label}
            </Button>
          ))}
        </div>
      ) : null}

      {interaction.kind === "text" ? (
        <div className="grid gap-2">
          <Textarea
            className="min-h-20"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Type your answer for the agent..."
          />
          <Button type="button" className="w-fit" disabled={disabled || !value.trim()} onClick={() => onRespond(value)}>
            <SendIcon data-icon="inline-start" />
            Send Answer
          </Button>
        </div>
      ) : null}

      {interaction.kind === "permission" || interaction.kind === "approval" ? (
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" disabled={disabled} onClick={() => onRespond("approve")}>
            Approve
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onRespond("approve", { remember: true })}>
            Approve + Remember
          </Button>
          <Button type="button" size="sm" variant="destructive" disabled={disabled} onClick={() => onRespond("reject")}>
            Reject
          </Button>
        </div>
      ) : null}
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
