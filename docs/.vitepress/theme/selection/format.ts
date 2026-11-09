export const pct = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : 'Not scored'
export const number = (value: unknown) => typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'Not recorded'
export const short = (id: unknown) => typeof id === 'string' ? id.slice(0, 10) : 'Not recorded'
export const size = (value: unknown) => Array.isArray(value) ? value.length : 0
export const selectedLabel = (node: any) => node?.selected ? 'Selected artifact' : node?.finalContent ? 'Matches final content' : ''
