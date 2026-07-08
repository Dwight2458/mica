"use client"

import { useCallback, useEffect, useState } from "react"
import { CheckIcon, ShieldAlertIcon, XIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { apiRequest, formatDate, type Approval } from "@/lib/api"

type ApprovalFilter = "all" | "pending" | "approved" | "rejected"
const filters: ApprovalFilter[] = ["all", "pending", "approved", "rejected"]

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [filter, setFilter] = useState<ApprovalFilter>("pending")
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const query = filter === "all" ? "" : `?status=${filter}`
      setApprovals(await apiRequest<Approval[]>(`/approvals${query}`))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load approvals")
    }
  }, [filter])

  useEffect(() => {
    void load()
    const interval = window.setInterval(() => void load(), 2000)
    return () => window.clearInterval(interval)
  }, [load])

  async function decide(id: string, decision: "approved" | "rejected") {
    await apiRequest<Approval>(`/approvals/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, resolved_by: "web", comment: `${decision} from UI` }),
    })
    await load()
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Command Approvals</h1>
        <p className="text-sm text-muted-foreground">
          High-risk external binary commands intercepted by Mica shims.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {filters.map((item) => (
          <Button
            key={item}
            size="sm"
            variant={filter === item ? "default" : "outline"}
            onClick={() => setFilter(item)}
          >
            {item}
          </Button>
        ))}
      </div>

      {error && <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">{error}</p>}

      <div className="grid gap-4">
        {approvals.map((approval) => (
          <Card key={approval.id}>
            <CardHeader>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <ShieldAlertIcon className="size-4 text-yellow-600" />
                    {approval.tool}
                  </CardTitle>
                  <CardDescription>{formatDate(approval.created_at)} - {approval.cwd}</CardDescription>
                </div>
                <StatusBadge status={approval.status} />
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-2 md:grid-cols-[160px_1fr]">
                <span className="text-sm text-muted-foreground">Command</span>
                <code className="rounded-lg bg-muted p-2 text-xs break-words">{approval.command_line}</code>
                <span className="text-sm text-muted-foreground">Risk</span>
                <span className="text-sm">{approval.risk_level}</span>
                <span className="text-sm text-muted-foreground">Reason</span>
                <span className="text-sm">{approval.reason}</span>
                <span className="text-sm text-muted-foreground">Arguments</span>
                <code className="rounded-lg bg-muted p-2 text-xs break-words">{JSON.stringify(approval.argv)}</code>
              </div>
              {approval.status === "pending" ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => void decide(approval.id, "approved")}>
                    <CheckIcon data-icon="inline-start" />
                    Approve
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => void decide(approval.id, "rejected")}>
                    <XIcon data-icon="inline-start" />
                    Reject
                  </Button>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  Resolved {formatDate(approval.resolved_at)} by {approval.resolved_by ?? "unknown"}
                  {approval.comment ? `: ${approval.comment}` : ""}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {!approvals.length && (
          <Card>
            <CardContent className="py-10 text-sm text-muted-foreground">
              No command approvals for this filter.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
