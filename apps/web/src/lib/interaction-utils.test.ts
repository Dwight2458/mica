import assert from "node:assert/strict"
import test from "node:test"

import {
  buildNativeAnswers,
  groupNativeQuestionOptions,
  hasCompleteNativeAnswers,
  toggleNativeAnswer,
} from "./interaction-utils.ts"

const options = [
  {
    id: "1:1",
    label: "React",
    value: "React",
    question_index: 0,
    question: "Which framework?",
    multiple: false,
  },
  {
    id: "1:2",
    label: "Vue",
    value: "Vue",
    question_index: 0,
    question: "Which framework?",
    multiple: false,
  },
  {
    id: "2:1",
    label: "Tests",
    value: "Tests",
    question_index: 1,
    question: "Which extras?",
    multiple: true,
  },
  {
    id: "2:2",
    label: "Docs",
    value: "Docs",
    question_index: 1,
    question: "Which extras?",
    multiple: true,
  },
]

test("groups native questions and preserves the multiple flag", () => {
  const groups = groupNativeQuestionOptions(options)

  assert.equal(groups.length, 2)
  assert.equal(groups[0].multiple, false)
  assert.equal(groups[1].multiple, true)
})

test("single-select replaces the answer while multi-select toggles answers", () => {
  let answers: Record<number, string[]> = {}

  answers = toggleNativeAnswer(answers, 0, "React", false)
  answers = toggleNativeAnswer(answers, 0, "Vue", false)
  assert.deepEqual(answers[0], ["Vue"])

  answers = toggleNativeAnswer(answers, 1, "Tests", true)
  answers = toggleNativeAnswer(answers, 1, "Docs", true)
  assert.deepEqual(answers[1], ["Tests", "Docs"])

  answers = toggleNativeAnswer(answers, 1, "Tests", true)
  assert.deepEqual(answers[1], ["Docs"])
})

test("builds ordered OpenCode answer arrays and requires one answer per question", () => {
  const groups = groupNativeQuestionOptions(options)
  const incomplete = { 0: ["React"] }
  const complete = { 0: ["React"], 1: ["Tests", "Docs"] }

  assert.equal(hasCompleteNativeAnswers(groups, incomplete), false)
  assert.equal(hasCompleteNativeAnswers(groups, complete), true)
  assert.deepEqual(buildNativeAnswers(groups, complete), [["React"], ["Tests", "Docs"]])
})
