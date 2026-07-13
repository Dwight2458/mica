import assert from "node:assert/strict"
import test from "node:test"

import { agentOutputText, runEventTypes } from "./run-utils.ts"

test("shows OpenCode assistant message parts in realtime logs", () => {
  const event = {
    event_type: "command_output",
    payload: {
      stream: "stdout",
      text: "Planning the implementation.",
      raw_event: {
        type: "opencode_message_part",
        part: { type: "text", text: "Planning the implementation." },
      },
    },
  }

  assert.equal(agentOutputText(event as never), "Planning the implementation.")
})

test("shows OpenCode tool state summaries when the tool has no output", () => {
  const event = {
    event_type: "command_output",
    payload: {
      stream: "agent",
      text: "OpenCode tool todowrite completed.",
      raw_event: {
        type: "tool_use",
        part: { type: "tool", tool: "todowrite", state: { status: "completed" } },
      },
    },
  }

  assert.equal(agentOutputText(event as never), "OpenCode tool todowrite completed.")
})

test("subscribes session pages to interaction lifecycle events", () => {
  assert.equal(runEventTypes.includes("interaction_required"), true)
  assert.equal(runEventTypes.includes("interaction_responded"), true)
  assert.equal(runEventTypes.includes("interaction_dismissed"), true)
})
