import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { ApprovalStatus } from "@/lib/api"

type StatusBadgeProps = {
  status: ApprovalStatus | string
}

const statusClasses: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200",
  started: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-200",
  policy_decision: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-200",
  waiting_approval: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200",
  completed: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-200",
  approved: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-200",
  failed: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200",
  rejected: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200",
  timeout: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200",
  cancelled: "bg-muted text-muted-foreground",
  agent_tool: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-200",
  runtime_internal: "bg-zinc-100 text-zinc-700 dark:bg-zinc-900 dark:text-zinc-200",
  external_binary: "bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-200",
  policy_gated: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200",
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <Badge variant="secondary" className={cn("border-transparent", statusClasses[status])}>
      {status.replace("_", " ")}
    </Badge>
  )
}
