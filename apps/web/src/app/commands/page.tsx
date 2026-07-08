"use client"

import { useCallback, useEffect, useState } from "react"

import { StatusBadge } from "@/components/status-badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { apiRequest, formatDate, formatDuration, type CommandRecord } from "@/lib/api"

export default function CommandsPage() {
  const [commands, setCommands] = useState<CommandRecord[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setCommands(await apiRequest<CommandRecord[]>("/commands"))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load command records")
    }
  }, [])

  useEffect(() => {
    void load()
    const interval = window.setInterval(() => void load(), 2000)
    return () => window.clearInterval(interval)
  }, [load])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Command Records</h1>
        <p className="text-sm text-muted-foreground">
          Audit trail for external binary commands observed by Mica shims.
        </p>
      </div>

      {error && <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Recent Commands</CardTitle>
        </CardHeader>
        <CardContent>
          {commands.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Command</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Approval</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {commands.map((command) => (
                  <TableRow key={command.id}>
                    <TableCell className="max-w-[360px] whitespace-normal">
                      <code className="break-words rounded bg-muted px-2 py-1 text-xs">{command.command_line}</code>
                      <div className="mt-1 text-xs text-muted-foreground">{command.cwd}</div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={command.status} />
                    </TableCell>
                    <TableCell>{command.risk_level}</TableCell>
                    <TableCell>{command.exit_code ?? "-"}</TableCell>
                    <TableCell>{formatDuration(command.duration_ms)}</TableCell>
                    <TableCell>{formatDate(command.started_at)}</TableCell>
                    <TableCell>
                      {command.approval_id ? (
                        <code className="rounded bg-muted px-2 py-1 text-xs">{command.approval_id}</code>
                      ) : (
                        "-"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-sm text-muted-foreground">No command records yet.</div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
