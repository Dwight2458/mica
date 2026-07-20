export type NativeQuestionOption = {
  id: string
  label: string
  value: string
  description?: string
  question_index?: number
  question?: string
  header?: string
  multiple?: boolean
}

export type NativeQuestionGroup = {
  index: number
  question: string
  header?: string
  multiple: boolean
  options: NativeQuestionOption[]
}

export function groupNativeQuestionOptions(options: NativeQuestionOption[]): NativeQuestionGroup[] {
  const groups = new Map<number, NativeQuestionGroup>()

  options.forEach((option) => {
    if (typeof option.question_index !== "number" || !option.question) return
    const group = groups.get(option.question_index) ?? {
      index: option.question_index,
      question: option.question,
      header: option.header,
      multiple: option.multiple === true,
      options: [],
    }
    group.multiple ||= option.multiple === true
    group.options.push(option)
    groups.set(option.question_index, group)
  })

  return Array.from(groups.values()).sort((left, right) => left.index - right.index)
}

export function toggleNativeAnswer(
  current: Record<number, string[]>,
  questionIndex: number,
  value: string,
  multiple: boolean,
): Record<number, string[]> {
  if (!multiple) {
    return { ...current, [questionIndex]: [value] }
  }

  const selected = current[questionIndex] ?? []
  const next = selected.includes(value) ? selected.filter((answer) => answer !== value) : [...selected, value]
  return { ...current, [questionIndex]: next }
}

export function hasCompleteNativeAnswers(
  groups: NativeQuestionGroup[],
  answers: Record<number, string[]>,
): boolean {
  return groups.every((group) => (answers[group.index]?.length ?? 0) > 0)
}

export function buildNativeAnswers(
  groups: NativeQuestionGroup[],
  answers: Record<number, string[]>,
): string[][] {
  return groups.map((group) => answers[group.index] ?? [])
}
