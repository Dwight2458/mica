import Link from "next/link"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import type { SessionMessage } from "@/lib/api"

export function SessionMessageView({ message }: { message: SessionMessage }) {
  const partType = metadataString(message, "part_type")
  if (partType === "tool") {
    const toolName = metadataString(message, "tool_name") ?? "tool"
    const toolStatus = metadataString(message, "tool_status") ?? "updated"
    const toolTitle = metadataString(message, "tool_title")
    return (
      <details className="rounded-md border bg-background/70 text-foreground">
        <summary className="cursor-pointer px-3 py-2 font-mono text-xs">
          {toolName} · {toolStatus}
        </summary>
        <div className="grid gap-2 border-t px-3 py-2 text-xs text-muted-foreground">
          <div className="whitespace-pre-wrap break-words">{toolTitle ?? message.content}</div>
          {message.run_id ? (
            <Link className="w-fit underline-offset-4 hover:underline" href={`/runs/${message.run_id}`}>
              Open raw evidence
            </Link>
          ) : null}
        </div>
      </details>
    )
  }

  return (
    <div className="min-w-0 break-words [&_a]:underline [&_a]:underline-offset-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-background/80 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-3 [&_h3]:font-semibold [&_li]:my-1 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:border [&_pre]:bg-background [&_pre]:p-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:p-2 [&_th]:border [&_th]:bg-background/70 [&_th]:p-2 [&_th]:text-left [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {message.content}
      </ReactMarkdown>
    </div>
  )
}

function metadataString(message: SessionMessage, key: string): string | null {
  const value = message.message_metadata[key]
  return typeof value === "string" && value ? value : null
}
