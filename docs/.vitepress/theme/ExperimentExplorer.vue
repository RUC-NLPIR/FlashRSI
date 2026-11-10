<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'

type SkillFile = { path: string; before: string; after: string; diff: string[] }
type Edit = { op: string; path: string; target?: string; content?: string }
type Candidate = {
  number: number; epoch: number; kind: string; accepted: boolean; score: number | null
  parentScore: number | null; bestScore: number; reason?: string; error?: string
  explanation?: string; edits: Edit[]; files: SkillFile[]
}
type Agent = {
  label: string; targetModel: string; workerModel: string
  splits: { train: number; dev: number; test: number }
  initialDev: number; accepted: number
  decisions: Candidate[]
  evaluations: { stage: string; tasks: number; finished: number; hard?: number; score?: number; f1: number }[]
  logs: { name: string; text: string }[]
}
type Archive = {
  schemaVersion: number; algorithm: string; benchmark: string; date: string; dateLabel: string
  seed: number; dataset: string; description: string; metric: string; scoreLabel?: string; agents: Record<string, Agent>
}

const props = defineProps<{ dataPath: string }>()

const data = ref<Archive | null>(null)
const error = ref('')
const agentKey = ref('miniagent')
const selected = ref(0)
const tab = ref('evolution')
const fileIndex = ref(0)
const fileView = ref('diff')
const logIndex = ref(0)
const logQuery = ref('')
const copyLabel = ref('Copy link')
const agent = computed(() => data.value?.agents[agentKey.value])
const candidate = computed(() => agent.value?.decisions[selected.value])
const skillFile = computed(() => candidate.value?.files[fileIndex.value])
const invalidCount = computed(() => agent.value?.decisions.filter(row => row.score === null).length || 0)
const epochCount = computed(() => new Set(agent.value?.decisions.map(row => row.epoch)).size)
const updateSchedule = computed(() => {
  const counts = new Map<string, number>()
  for (const row of agent.value?.decisions || []) counts.set(row.kind, (counts.get(row.kind) || 0) + 1)
  return [...counts].map(([kind, count]) => `${count} ${kind}`).join(' · ')
})
const pct = (score: number | null | undefined) => score == null ? 'Not recorded' : `${(score * 100).toFixed(2)}%`
const status = (row: Candidate) => row.score === null ? 'Invalid edit' : row.accepted ? 'Accepted' : 'Rejected'
const statusClass = (row: Candidate) => row.score === null ? 'invalid' : row.accepted ? 'accepted' : 'rejected'

async function load() {
  error.value = ''
  try {
    const response = await fetch(withBase(props.dataPath))
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const archive: Archive = await response.json()
    if (archive.schemaVersion !== 1 || !Object.keys(archive.agents).length) throw new Error('unsupported or empty experiment archive')
    const params = new URLSearchParams(window.location.search)
    const requested = params.get('agent') || ''
    agentKey.value = Object.hasOwn(archive.agents, requested) ? requested : Object.keys(archive.agents)[0]
    data.value = archive
    selected.value = Math.min(agent.value!.decisions.length - 1, Math.max(0, Number(params.get('candidate')) - 1 || 0))
  } catch (failure) {
    error.value = `Could not load the experiment records (${failure instanceof Error ? failure.message : 'network error'}).`
  }
}
onMounted(load)
function selectCandidate(index: number) {
  selected.value = index
  fileIndex.value = 0
  fileView.value = 'diff'
  copyLabel.value = 'Copy link'
}
function chooseAgent(key: string) {
  agentKey.value = key
  selectCandidate(0)
  logIndex.value = 0
}
async function copyLink() {
  const url = new URL(window.location.href)
  url.searchParams.set('agent', agentKey.value)
  url.searchParams.set('candidate', String(selected.value + 1))
  try {
    await navigator.clipboard.writeText(url.toString())
    copyLabel.value = 'Link copied'
  } catch {
    window.history.replaceState(null, '', url)
    copyLabel.value = 'Link in address bar'
  }
}

const chart = computed(() => {
  if (!agent.value) return { ticks: [], best: '', candidates: [], baseline: 0 }
  const a = agent.value
  const scores = [a.initialDev, ...a.decisions.flatMap(row => row.score === null ? [] : [row.score])]
  const low = Math.floor((Math.min(...scores) - 0.01) / 0.05) * 0.05
  const high = Math.ceil((Math.max(...scores) + 0.01) / 0.05) * 0.05
  const y = (score: number) => 184 - (score - low) / (high - low) * 158
  const x = (index: number) => 57 + index / a.decisions.length * 820
  const ticks = Array.from({ length: 5 }, (_, i) => {
    const value = low + (high - low) * i / 4
    return { label: `${(value * 100).toFixed(0)}%`, y: y(value) }
  })
  let best = `M ${x(0)} ${y(a.initialDev)}`
  a.decisions.forEach((row, i) => { best += ` H ${x(i + 1)} V ${y(row.bestScore)}` })
  const candidates = a.decisions.flatMap((row, i) => row.score === null ? [] : [{ ...row, index: i, x: x(i + 1), y: y(row.score) }])
  return { ticks, best, candidates, baseline: y(a.initialDev) }
})
const logLines = computed(() => {
  const lines = agent.value?.logs[logIndex.value]?.text.split('\n') || []
  const search = logQuery.value.toLocaleLowerCase().trim()
  return lines.map((text, index) => ({ text, number: index + 1 })).filter(line => !search || line.text.toLocaleLowerCase().includes(search))
})
</script>

<template>
  <main class="experiment-explorer">
    <header class="explorer-heading">
      <div>
        <p class="eyebrow">FlashRSI / Experiment explorer <span class="pilot">01 · Pilot</span></p>
        <h1>{{ data?.algorithm || 'Experiment' }} <span class="times">×</span> {{ data?.benchmark || 'archive' }}</h1>
        <p class="lead">Follow the edits. Inspect the evidence.</p>
      </div>
      <div class="run-stamp"><span class="archive-dot"></span> Historical run<br><small>{{ data?.dateLabel || 'Historical archive' }}<template v-if="data"> · Seed {{ data.seed }}</template></small></div>
    </header>
    <div v-if="!agent" class="load-state" role="status">
      <p>{{ error || 'Loading the experiment archive…' }}</p>
      <button v-if="error" class="plain-button" @click="load">Retry</button>
    </div>
    <template v-else>
      <section class="run-toolbar" aria-label="Harness selection">
        <div class="segmented">
          <button v-for="(value, key) in data!.agents" :key="key" :class="{ active: agentKey === key }" :aria-pressed="agentKey === key" @click="chooseAgent(String(key))">{{ value.label }}</button>
        </div>
        <p><span>Target</span> {{ agent.targetModel }} <span class="separator">/</span> <span>Worker</span> {{ agent.workerModel }}</p>
      </section>

      <section class="metrics" aria-label="Run results">
        <div class="metric"><span>Initial dev score</span><strong>{{ pct(agent.initialDev) }}</strong><small>{{ agent.splits.dev }} development tasks</small></div>
        <div class="metric"><span>Selected dev score</span><strong>{{ pct(agent.decisions[agent.decisions.length - 1].bestScore) }}</strong><small>After the last candidate decision</small></div>
        <div class="metric"><span>Accepted edits</span><strong>{{ agent.accepted }} <em>/ {{ agent.decisions.length }}</em></strong><small>{{ invalidCount }} invalid · {{ agent.decisions.length - agent.accepted - invalidCount }} rejected</small></div>
        <div class="metric"><span>Candidate updates</span><strong>{{ agent.decisions.length }} <em>edits</em></strong><small>{{ updateSchedule }}</small></div>
      </section>

      <nav class="explorer-tabs" aria-label="Experiment views">
        <button v-for="item in [{ id: 'evolution', label: 'Evolution' }, { id: 'logs', label: 'Run logs' }, { id: 'about', label: 'Run details' }]" :key="item.id" :class="{ active: tab === item.id }" :aria-current="tab === item.id ? 'page' : undefined" @click="tab = item.id">{{ item.label }}<span v-if="item.id === 'logs'">{{ agent.logs.length }}</span></button>
      </nav>

      <section v-if="tab === 'evolution'" class="evolution-view">
        <div class="chart-panel">
          <div class="section-heading"><div><h2>Development trajectory</h2><p>Each dot is a scored candidate. Click one to inspect its changes.</p></div><div class="legend"><span><i class="legend-line"></i> Incumbent</span><span><i class="legend-dot"></i> Candidate</span><span><i class="legend-dot accepted-dot"></i> Accepted</span></div></div>
          <svg class="trajectory-chart" viewBox="0 0 920 230" role="group" aria-label="Candidate development scores. Select a scored point to inspect the edit.">
            <g v-for="tick in chart.ticks" :key="tick.label"><line x1="57" :y1="tick.y" x2="877" :y2="tick.y" class="chart-grid" /><text x="43" :y="tick.y + 4" text-anchor="end" class="axis-label">{{ tick.label }}</text></g>
            <line x1="57" :y1="chart.baseline" x2="877" :y2="chart.baseline" class="baseline-line" />
            <path :d="chart.best" class="best-line" />
            <circle v-for="point in chart.candidates" :key="point.number" :cx="point.x" :cy="point.y" :r="selected === point.index ? 6 : point.accepted ? 4.5 : 3.5" :class="['candidate-point', { accepted: point.accepted, selected: selected === point.index }]" role="button" tabindex="0" :aria-label="`Candidate ${point.number}: ${pct(point.score!)}, ${status(point)}`" @click="selectCandidate(point.index)" @keydown.enter.prevent="selectCandidate(point.index)" @keydown.space.prevent="selectCandidate(point.index)"><title>{{ `#${point.number} · ${point.kind} · ${pct(point.score!)} · ${status(point)}` }}</title></circle>
            <text x="57" y="207" class="axis-label">Initial</text><text v-for="fraction in [0.25, 0.5, 0.75, 1]" :key="fraction" :x="57 + Math.round(agent.decisions.length * fraction) / agent.decisions.length * 820" y="207" text-anchor="middle" class="axis-label">{{ Math.round(agent.decisions.length * fraction) }}</text><text x="877" y="225" text-anchor="end" class="axis-caption">Candidate decision →</text>
          </svg>
          <p class="chart-note">Dev: {{ agent.splits.dev }} tasks · Test is held out from selection · Invalid edits have no score and are listed below.</p>
        </div>

        <div class="candidate-workspace">
          <aside class="candidate-list" aria-label="Candidate decisions">
            <div class="list-heading"><h2>Candidate decisions</h2><span>{{ agent.decisions.length }}</span></div>
            <div class="candidate-scroll">
              <button v-for="(row, index) in agent.decisions" :key="row.number" :class="['candidate-row', { selected: selected === index }]" :aria-pressed="selected === index" @click="selectCandidate(index)">
                <span class="candidate-number">{{ String(row.number).padStart(2, '0') }}</span>
                <span class="candidate-row-body"><strong>Epoch {{ row.epoch + 1 }} <span>{{ row.kind }}</span></strong><small :class="statusClass(row)">{{ status(row) }}</small></span>
                <span class="candidate-score">{{ row.score === null ? '—' : pct(row.score) }}</span>
              </button>
            </div>
          </aside>
          <section v-if="candidate" class="candidate-detail" aria-live="polite">
            <header class="detail-heading"><div><p class="eyebrow">Epoch {{ candidate.epoch + 1 }} / {{ candidate.kind }} update</p><h2>Candidate {{ String(candidate.number).padStart(2, '0') }} <span :class="['status-badge', statusClass(candidate)]">{{ status(candidate) }}</span></h2></div><button class="plain-button" @click="copyLink">{{ copyLabel }}</button></header>
            <div class="decision-facts"><div><span>Candidate dev</span><strong>{{ candidate.score === null ? 'Not scored' : pct(candidate.score) }}</strong></div><div><span>Parent dev</span><strong>{{ candidate.parentScore === null ? 'Not recorded' : pct(candidate.parentScore) }}</strong></div><div><span>Selected dev after decision</span><strong>{{ pct(candidate.bestScore) }}</strong></div></div>
            <div v-if="candidate.error" class="failure-note"><strong>{{ candidate.reason === 'invalid_patch' ? 'Invalid edit' : candidate.reason }}</strong><p>{{ candidate.error }}</p></div>
            <div class="worker-note"><h3>Recorded edit rationale</h3><p>{{ candidate.explanation || 'No edit rationale was preserved in this decision record.' }}</p></div>
            <template v-if="candidate.files.length">
              <div class="file-toolbar"><label>File <select v-model="fileIndex"><option v-for="(file, index) in candidate.files" :key="file.path" :value="index">{{ file.path }}</option></select></label><div class="segmented compact"><button v-for="view in ['diff', 'before', 'after']" :key="view" :class="{ active: fileView === view }" :aria-pressed="fileView === view" @click="fileView = view">{{ view }}</button></div></div>
              <div v-if="skillFile" class="code-view" tabindex="0" :aria-label="`${fileView} for ${skillFile.path}`"><pre v-if="fileView === 'diff'" class="diff-code"><code><span v-for="(line, index) in skillFile.diff" :key="index" :class="{ addition: line.startsWith('+') && !line.startsWith('+++'), removal: line.startsWith('-') && !line.startsWith('---'), hunk: line.startsWith('@@') }">{{ line || ' ' }}{{ '\n' }}</span><span v-if="!skillFile.diff.length">No textual change.</span></code></pre><pre v-else><code>{{ fileView === 'before' ? skillFile.before : skillFile.after }}</code></pre></div>
            </template>
            <div v-else class="empty-detail">No scored candidate version was created for this edit.</div>
            <details v-if="candidate.edits.length" class="proposed-edits"><summary>Proposed edit operations <span>{{ candidate.edits.length }}</span></summary><div v-for="(edit, index) in candidate.edits" :key="index"><h4>{{ index + 1 }}. {{ edit.op }} · {{ edit.path }}</h4><pre v-if="edit.target"><code>{{ edit.target }}</code></pre><pre v-if="edit.content"><code>{{ edit.content }}</code></pre></div></details>
          </section>
        </div>
      </section>

      <section v-else-if="tab === 'logs'" class="logs-view">
        <div class="section-heading"><div><h2>Runtime logs</h2><p>Historical progress, retries, and recovery output. Test result summaries are omitted; these are not complete model conversation transcripts.</p></div></div>
        <div class="filter-bar"><label class="log-select-label">Log file<select v-model="logIndex"><option v-for="(log, index) in agent.logs" :key="log.name" :value="index">{{ log.name }}</option></select></label><label class="search-label"><span>Filter lines</span><input v-model="logQuery" type="search" placeholder="Search within this log…" /></label><span class="result-count">{{ logLines.length.toLocaleString() }} lines</span></div>
        <div class="log-reader" tabindex="0" aria-label="Runtime log lines"><div v-for="line in logLines" :key="line.number" class="log-line"><span>{{ line.number }}</span><code>{{ line.text || ' ' }}</code></div><p v-if="!logLines.length" class="empty-detail">No log lines match this search.</p></div>
      </section>

      <section v-else class="about-view">
        <div class="section-heading"><div><h2>About this experiment</h2><p>{{ data!.description }}</p></div></div>
        <dl class="run-metadata"><div><dt>Dataset</dt><dd>{{ data!.dataset }}</dd></div><div><dt>Splits</dt><dd>{{ agent.splits.train }} train / {{ agent.splits.dev }} dev / {{ agent.splits.test }} test</dd></div><div><dt>Update schedule</dt><dd>{{ epochCount }} epochs · {{ updateSchedule }} decisions</dd></div><div><dt>Selection</dt><dd>Dev only · sealed test after selection</dd></div><div><dt>Primary metric</dt><dd>{{ data!.metric }}</dd></div><div><dt>Models</dt><dd>Target: {{ agent.targetModel }}<br>Worker: {{ agent.workerModel }}</dd></div></dl>
        <div class="scope-note"><h3>What is preserved here</h3><p>Candidate decisions, recorded edit rationale, archived skill versions, development evaluation summaries, and runtime logs. Test results are not displayed in this explorer. Epochs are displayed from 1; the original records use zero-based epochs.</p><p>These curated records do not include every Worker prompt or Target tool call. Invalid edits are kept without a score. This page displays recorded results and does not rerun models.</p></div>
        <details class="evaluation-ledger"><summary>Evaluation ledger <span>{{ agent.evaluations.length }} records</span></summary><div class="table-scroll"><table><thead><tr><th>#</th><th>Stage</th><th>Tasks / finished</th><th>{{ data?.scoreLabel || 'Hard score' }}</th><th>F1</th></tr></thead><tbody><tr v-for="(row, index) in agent.evaluations" :key="index"><td>{{ index + 1 }}</td><td>{{ row.stage }}</td><td>{{ row.tasks }} / {{ row.finished }}</td><td>{{ pct(row.score ?? row.hard) }}</td><td>{{ pct(row.f1) }}</td></tr></tbody></table></div></details>
      </section>
      <footer class="explorer-footer"><span>FlashRSI · Inspectable evolution</span><span>Historical evidence · {{ data!.date }} · Seed {{ data!.seed }}</span></footer>
    </template>
  </main>
</template>

<style scoped>
.experiment-explorer { max-width: 1320px; margin: 0 auto; padding: 48px 36px 32px; color: var(--vp-c-text-1); font-size: 14px; line-height: 1.6; }
.explorer-heading { display: flex; justify-content: space-between; align-items: center; gap: 24px; margin-bottom: 32px; }
.eyebrow { margin: 0 0 10px; color: var(--vp-c-text-2); font-size: 11px; font-weight: 650; letter-spacing: .09em; text-transform: uppercase; }
.pilot { display: inline-block; margin-left: 12px; padding: 2px 7px; border: 1px solid var(--vp-c-divider); border-radius: 4px; color: var(--vp-c-brand-1); letter-spacing: .04em; }
h1 { margin: 0; font-size: clamp(30px, 4vw, 46px); line-height: 1.15; letter-spacing: -.045em; font-weight: 650; }
.times { padding: 0 5px; color: var(--vp-c-brand-1); font-weight: 400; }
.lead { margin: 12px 0 0; color: var(--vp-c-text-2); font-size: 16px; }
.run-stamp { text-align: right; font-size: 12px; line-height: 1.9; white-space: nowrap; }
.run-stamp small { color: var(--vp-c-text-2); font-size: 11px; }
.archive-dot { display: inline-block; width: 6px; height: 6px; margin-right: 6px; background: var(--vp-c-brand-1); border-radius: 50%; }
.run-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.run-toolbar p { color: var(--vp-c-text-1); font-size: 11px; }
.run-toolbar p span { color: var(--vp-c-text-2); }
.separator { padding: 0 10px; }
.segmented { display: inline-flex; flex-shrink: 0; padding: 4px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg-alt); border-radius: 8px; }
.segmented button { padding: 6px 18px; color: var(--vp-c-text-2); border: 1px solid transparent; border-radius: 5px; font-size: 13px; font-weight: 550; }
.segmented button.active { color: var(--vp-c-text-1); background: var(--vp-c-bg-elv); border-color: var(--vp-c-divider); box-shadow: 0 1px 2px #00000005; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg-elv); border-radius: 10px; overflow: hidden; }
.metric { padding: 20px 24px; border-left: 1px solid var(--vp-c-divider); }
.metric:first-child { border-left: 0; }
.metric > span { display: block; font-size: 11px; color: var(--vp-c-text-2); }
.metric > strong { display: block; margin: 9px 0 5px; font-size: 32px; font-weight: 600; line-height: 1.2; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.metric em { font-size: 18px; font-style: normal; color: var(--vp-c-text-3); font-weight: 400; }
.metric small { font-size: 11px; color: var(--vp-c-text-2); }
.explorer-tabs { display: flex; gap: 28px; margin: 26px 0; border-bottom: 1px solid var(--vp-c-divider); }
.explorer-tabs button { padding: 10px 0 12px; border-bottom: 2px solid transparent; color: var(--vp-c-text-2); font-size: 13px; white-space: nowrap; }
.explorer-tabs button.active { color: var(--vp-c-brand-1); border-color: var(--vp-c-brand-1); font-weight: 600; }
.explorer-tabs button span { margin-left: 7px; font-size: 10px; color: var(--vp-c-text-3); }
.section-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
h2 { margin: 0; font-size: 16px; font-weight: 600; letter-spacing: -.02em; }
.section-heading p { margin: 5px 0 0; color: var(--vp-c-text-2); font-size: 12px; }
.chart-panel { border: 1px solid var(--vp-c-divider); border-radius: 10px; background: var(--vp-c-bg-elv); padding: 22px 24px 14px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; padding-top: 5px; font-size: 10px; color: var(--vp-c-text-2); }
.legend > span { display: flex; align-items: center; gap: 5px; }
.legend-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #9ca3aa; }
.accepted-dot { background: var(--vp-c-brand-1); }
.legend-line { display: inline-block; width: 13px; border-top: 2px solid var(--vp-c-brand-1); }
.trajectory-chart { display: block; width: 100%; margin-top: 10px; overflow: visible; }
.chart-grid { stroke: var(--vp-c-divider-light); stroke-width: 1; }
.axis-label, .axis-caption { fill: var(--vp-c-text-2); font-size: 10px; font-family: var(--vp-font-family-base); }
.axis-caption { font-size: 9px; }
.baseline-line { stroke: var(--vp-c-text-3); stroke-width: .8; stroke-dasharray: 4 5; opacity: .6; }
.best-line { fill: none; stroke: var(--vp-c-brand-1); stroke-width: 2; }
.candidate-point { fill: #a0a6ae; stroke: var(--vp-c-bg-elv); stroke-width: 1.2; cursor: pointer; }
.candidate-point.accepted { fill: var(--vp-c-brand-1); }
.candidate-point.selected { stroke: var(--vp-c-text-1); stroke-width: 2; }
.candidate-point:focus { outline: 2px solid var(--vp-c-brand-1); outline-offset: 4px; }
.chart-note { margin: 0; font-size: 10px; color: var(--vp-c-text-2); }
.candidate-workspace { display: grid; grid-template-columns: 290px minmax(0, 1fr); gap: 20px; margin-top: 22px; align-items: start; }
.candidate-list { border: 1px solid var(--vp-c-divider); border-radius: 9px; overflow: hidden; background: var(--vp-c-bg-elv); }
.list-heading { display: flex; align-items: center; justify-content: space-between; padding: 17px 18px; border-bottom: 1px solid var(--vp-c-divider); }
.list-heading h2 { font-size: 13px; }
.list-heading > span { color: var(--vp-c-text-3); font-size: 11px; }
.candidate-scroll { max-height: 690px; overflow-y: auto; overscroll-behavior: contain; }
.candidate-row { display: flex; width: 100%; align-items: center; gap: 12px; padding: 12px 15px; border-bottom: 1px solid var(--vp-c-divider-light); text-align: left; border-left: 3px solid transparent; }
.candidate-row:hover { background: var(--vp-c-bg-soft); }
.candidate-row.selected { border-left-color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); }
.candidate-number { color: var(--vp-c-text-3); font-family: var(--vp-font-family-mono); font-size: 11px; }
.candidate-row-body { flex: 1; }
.candidate-row-body strong { display: block; font-size: 12px; font-weight: 500; }
.candidate-row-body strong span { color: var(--vp-c-text-2); font-size: 10px; margin-left: 6px; }
.candidate-row-body small { display: block; font-size: 10px; margin-top: 2px; }
.candidate-score { font-size: 12px; font-variant-numeric: tabular-nums; font-weight: 550; }
.rejected { color: var(--vp-c-text-2); }
.invalid, .regressed { color: #ad5d52; }
.candidate-detail { border: 1px solid var(--vp-c-divider); border-radius: 9px; background: var(--vp-c-bg-elv); padding: 24px; min-width: 0; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.detail-heading .eyebrow { font-size: 10px; margin-bottom: 7px; }
.detail-heading h2 { display: flex; align-items: center; gap: 12px; font-size: 21px; }
.plain-button { border: 1px solid var(--vp-c-divider); border-radius: 5px; padding: 6px 12px; font-size: 11px; white-space: nowrap; color: var(--vp-c-text-2); }
.plain-button:hover { background: var(--vp-c-bg-soft); color: var(--vp-c-text-1); }
.plain-button:disabled { opacity: .35; cursor: not-allowed; }
.status-badge { padding: 3px 8px; border: 1px solid var(--vp-c-divider); border-radius: 4px; font-size: 10px; letter-spacing: 0; font-weight: 500; }
.status-badge.accepted { border-color: #347a5d40; background: #347a5d0c; }
.decision-facts { display: grid; grid-template-columns: 1fr 1fr 1.5fr; gap: 12px; margin: 22px 0; padding: 16px 0; border-block: 1px solid var(--vp-c-divider-light); }
.decision-facts span { display: block; color: var(--vp-c-text-2); font-size: 10px; }
.decision-facts strong { display: block; font-size: 16px; font-weight: 550; margin-top: 3px; font-variant-numeric: tabular-nums; }
h3 { font-size: 12px; font-weight: 600; margin: 0 0 8px; }
.worker-note p { margin: 0; color: var(--vp-c-text-2); font-size: 12px; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.failure-note { padding: 12px 16px; border: 1px solid #ad5d5240; border-radius: 5px; background: #ad5d5209; color: #ad5d52; font-size: 12px; margin-bottom: 20px; }
.failure-note p { margin: 5px 0 0; }
.file-toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-top: 24px; padding: 11px 0; }
label { display: flex; align-items: center; gap: 9px; font-size: 11px; color: var(--vp-c-text-2); min-width: 0; }
select, input { color: var(--vp-c-text-1); border: 1px solid var(--vp-c-divider); border-radius: 5px; background: var(--vp-c-bg-elv); font-family: inherit; font-size: 12px; padding: 7px 9px; min-width: 0; }
.file-toolbar select { max-width: 270px; font-family: var(--vp-font-family-mono); font-size: 10px; }
.segmented.compact { padding: 2px; border-radius: 5px; }
.compact button { padding: 3px 10px; font-size: 10px; text-transform: capitalize; }
.code-view { max-height: 530px; overflow: auto; background: var(--vp-c-bg-alt); border: 1px solid var(--vp-c-divider); border-radius: 6px; font-size: 11px; line-height: 1.8; }
pre { margin: 0; font-family: var(--vp-font-family-mono); tab-size: 2; }
.code-view pre { min-width: 100%; width: max-content; padding: 14px 0; }
.code-view pre:not(.diff-code) { padding: 14px 16px; }
.diff-code code > span { display: block; min-width: 100%; padding: 0 14px; }
.diff-code .addition { background: #347a5d14; color: #347a5d; }
.diff-code .removal { background: #ad5d5215; color: #ad5d52; }
.diff-code .hunk { color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); }
.proposed-edits { margin-top: 20px; font-size: 12px; }
summary { cursor: pointer; font-size: 12px; font-weight: 550; padding: 12px 0; }
summary span { margin-left: 9px; color: var(--vp-c-text-3); font-size: 11px; font-weight: 400; }
.proposed-edits h4 { margin: 14px 0 8px; font-size: 11px; font-weight: 600; overflow-wrap: anywhere; }
.proposed-edits pre { padding: 12px; background: var(--vp-c-bg-alt); border-radius: 4px; font-size: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.empty-detail { padding: 28px 12px; text-align: center; font-size: 12px; color: var(--vp-c-text-2); }
.filter-bar { display: flex; gap: 20px; align-items: center; margin: 22px 0 16px; flex-wrap: wrap; }
.search-label { flex: 1; }
.search-label input { width: 100%; }
.result-count { font-size: 11px; color: var(--vp-c-text-2); margin-left: auto; }
.table-scroll { width: 100%; overflow: auto; border: 1px solid var(--vp-c-divider); border-radius: 7px; }
table { width: 100%; border-collapse: collapse; background: var(--vp-c-bg-elv); text-align: left; font-size: 12px; }
th { padding: 12px 16px; font-size: 10px; font-weight: 600; color: var(--vp-c-text-2); background: var(--vp-c-bg-alt); white-space: nowrap; }
td { padding: 14px 16px; border-top: 1px solid var(--vp-c-divider-light); vertical-align: top; }
.log-select-label select { max-width: 340px; }
.log-reader { max-height: 650px; overflow: auto; border: 1px solid var(--vp-c-divider); border-radius: 7px; background: #1d2024; color: #dbdcd9; padding: 14px 0; font-size: 10px; line-height: 1.8; }
.log-line { display: flex; width: max-content; min-width: 100%; }
.log-line > span { display: inline-block; flex: 0 0 54px; text-align: right; padding: 0 12px; color: #8b9298; user-select: none; font-family: var(--vp-font-family-mono); }
.log-line code { white-space: pre; padding-right: 20px; }
.run-metadata { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--vp-c-divider); border-radius: 7px; background: var(--vp-c-bg-elv); margin-top: 24px; }
.run-metadata > div { padding: 18px 22px; border-bottom: 1px solid var(--vp-c-divider-light); }
dt { font-size: 10px; color: var(--vp-c-text-2); margin-bottom: 5px; }
dd { margin: 0; font-size: 13px; }
.scope-note { margin: 26px 0; max-width: 780px; }
.scope-note p { color: var(--vp-c-text-2); font-size: 12px; }
.evaluation-ledger { padding-top: 10px; border-top: 1px solid var(--vp-c-divider); }
.evaluation-ledger .table-scroll { max-height: 420px; }
.explorer-footer { display: flex; justify-content: space-between; gap: 16px; margin-top: 36px; padding-top: 18px; border-top: 1px solid var(--vp-c-divider); color: var(--vp-c-text-3); font-size: 10px; }
.load-state { padding: 80px 20px; text-align: center; color: var(--vp-c-text-2); }
button:focus-visible, select:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--vp-c-brand-1); outline-offset: 3px; }
:global(.dark) .accepted, :global(.dark) .diff-code .addition { color: #8bc5a5; }
:global(.dark) .invalid, :global(.dark) .diff-code .removal { color: #e7a69b; }
@media (max-width: 1000px) {
  .experiment-explorer { padding: 32px 24px; }
  .run-toolbar { align-items: flex-start; flex-direction: column; gap: 8px; }
  .metric { padding: 18px; }
  .metric > strong { font-size: 28px; }
  .candidate-workspace { grid-template-columns: 240px minmax(0, 1fr); gap: 14px; }
  .candidate-detail { padding: 18px; }
  .file-toolbar { flex-wrap: wrap; }
  .section-heading { flex-direction: column; gap: 8px; }
}
@media (max-width: 700px) {
  .experiment-explorer { padding: 26px 16px; }
  .explorer-heading { align-items: flex-start; flex-direction: column; gap: 18px; margin-bottom: 24px; }
  .run-stamp { text-align: left; }
  .run-stamp br { display: none; }
  .run-stamp small { margin-left: 12px; }
  .metrics { grid-template-columns: repeat(2, 1fr); }
  .metric { padding: 16px; }
  .metric:nth-child(3) { border-left: 0; }
  .metric:nth-child(n + 3) { border-top: 1px solid var(--vp-c-divider); }
  .metric > strong { font-size: 27px; }
  .explorer-tabs { gap: 20px; overflow-x: auto; margin: 20px 0; }
  .explorer-tabs button { font-size: 12px; }
  .explorer-tabs button span { display: none; }
  .chart-panel { padding: 16px 12px 12px; }
  .trajectory-chart { min-height: 135px; }
  .chart-note { font-size: 9px; }
  .candidate-workspace { display: block; }
  .candidate-list { margin-bottom: 16px; }
  .candidate-scroll { max-height: 220px; }
  .candidate-row { padding: 10px 15px; }
  .candidate-detail { padding: 16px; }
  .detail-heading h2 { font-size: 18px; gap: 8px; }
  .detail-heading .plain-button { padding: 5px 8px; font-size: 10px; }
  .decision-facts { gap: 10px; }
  .decision-facts strong { font-size: 14px; }
  .decision-facts span { font-size: 9px; }
  .file-toolbar select { max-width: 235px; }
  .filter-bar { gap: 12px; }
  .search-label { flex-basis: 100%; }
  .log-select-label { width: 100%; }
  .log-select-label select { width: 100%; }
  .run-metadata { grid-template-columns: 1fr; }
  .explorer-footer { flex-direction: column; gap: 5px; }
}
</style>
