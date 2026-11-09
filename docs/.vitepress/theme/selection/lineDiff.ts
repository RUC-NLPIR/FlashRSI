export type DiffLine = {
  kind: 'context' | 'add' | 'remove' | 'gap'
  text: string
  before?: number
  after?: number
  omitted?: number
}

const lines = (text?: string) => text === undefined || text === '' ? [] : text.replaceAll('\r\n', '\n').split('\n')

/** A line diff for display; large unrelated files use a complete replacement. */
export function lineDiff(before?: string, after?: string): DiffLine[] {
  const left = lines(before), right = lines(after)
  let prefix = 0, suffix = 0
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) prefix++
  while (suffix < left.length - prefix && suffix < right.length - prefix && left[left.length - 1 - suffix] === right[right.length - 1 - suffix]) suffix++
  const old = left.slice(prefix, left.length - suffix)
  const next = right.slice(prefix, right.length - suffix)
  const result: DiffLine[] = []
  let oldLine = 1, newLine = 1
  const context = (text: string) => result.push({ kind: 'context', text, before: oldLine++, after: newLine++ })
  const remove = (text: string) => result.push({ kind: 'remove', text, before: oldLine++ })
  const add = (text: string) => result.push({ kind: 'add', text, after: newLine++ })
  for (let i = 0; i < prefix; i++) context(left[i])
  // Keep comparisons bounded on phones; a replacement still preserves both files.
  if (old.length * next.length > 2_000_000) {
    old.forEach(remove)
    next.forEach(add)
  } else {
    const width = next.length + 1
    const lcs = new Uint32Array((old.length + 1) * width)
    for (let i = old.length - 1; i >= 0; i--) {
      for (let j = next.length - 1; j >= 0; j--) {
        lcs[i * width + j] = old[i] === next[j] ? lcs[(i + 1) * width + j + 1] + 1 : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1])
      }
    }
    let i = 0, j = 0
    while (i < old.length || j < next.length) {
      if (i < old.length && j < next.length && old[i] === next[j]) context(old[i++]), j++
      else if (i < old.length && (j === next.length || lcs[(i + 1) * width + j] >= lcs[i * width + j + 1])) remove(old[i++])
      else add(next[j++])
    }
  }
  for (let i = left.length - suffix; i < left.length; i++) context(left[i])
  return result
}

/** Collapse unchanged spans while retaining the context around every change. */
export function compactDiff(input: DiffLine[], context = 3): DiffLine[] {
  const result: DiffLine[] = []
  let index = 0
  while (index < input.length) {
    if (input[index].kind !== 'context') { result.push(input[index++]); continue }
    const start = index
    while (index < input.length && input[index].kind === 'context') index++
    const run = input.slice(start, index)
    const head = start > 0 ? Math.min(context, run.length) : 0
    const tail = index < input.length ? Math.min(context, run.length - head) : 0
    if (run.length <= head + tail + 1) result.push(...run)
    else {
      result.push(...run.slice(0, head))
      result.push({ kind: 'gap', text: `${run.length - head - tail} unchanged lines`, omitted: run.length - head - tail })
      if (tail) result.push(...run.slice(run.length - tail))
    }
  }
  return result
}
