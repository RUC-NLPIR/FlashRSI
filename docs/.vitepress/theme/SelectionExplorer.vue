<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import { pct, short } from './selection/format'
import { compactDiff, lineDiff } from './selection/lineDiff'
import './selection/style.css'

const props = defineProps<{ dataPath: string }>()
const views = {
  opro: defineAsyncComponent(() => import('./selection/OPRO.vue')),
  evoprompt: defineAsyncComponent(() => import('./selection/EvoPrompt.vue')),
  gepa: defineAsyncComponent(() => import('./selection/GEPA.vue')),
  ace: defineAsyncComponent(() => import('./selection/ACE.vue')),
  ahe: defineAsyncComponent(() => import('./selection/AHE.vue')),
  adas: defineAsyncComponent(() => import('./selection/ADAS.vue')),
  meta_harness: defineAsyncComponent(() => import('./selection/MetaHarness.vue')),
  darwinx: defineAsyncComponent(() => import('./selection/DarwinX.vue')),
  modular_rsi: defineAsyncComponent(() => import('./selection/ModularRSI.vue')),
  rrsi: defineAsyncComponent(() => import('./selection/RRSI.vue')),
  evoharness: defineAsyncComponent(() => import('./selection/EvoHarness.vue')),
}
const data = ref<any>(null)
const agentKey = ref('miniagent')
const tab = ref('selection')
const error = ref('')
const agent = computed(() => data.value?.agents[agentKey.value])
const methodView = computed(() => views[data.value?.key as keyof typeof views])
const eventFilter = ref('')
const events = computed(() => (agent.value?.events || []).filter((event: any) => JSON.stringify(event).toLowerCase().includes(eventFilter.value.toLowerCase())))
const resourceData = ref<any>(null)
const resourceError = ref('')
const resourceId = ref('')
const compareId = ref('')
const file = ref('')
const resourceCache = new Map<string, any>()
const copyText = ref('Copy resource link')
const inlineChanges = ref(false)
const resourcePanel = ref<HTMLElement | null>(null)
const fileView = ref('diff')
const showAllLines = ref(false)
let selectionScroll = 0
const current = computed(() => resourceData.value && Object.hasOwn(resourceData.value.states, resourceId.value) ? resourceData.value.states[resourceId.value] : undefined)
const previous = computed(() => resourceData.value && Object.hasOwn(resourceData.value.states, compareId.value) ? resourceData.value.states[compareId.value] : undefined)
const paths = computed(() => [...new Set([...Object.keys(previous.value?.files || {}), ...Object.keys(current.value?.files || {})])].sort() as string[])
const before = computed(() => resourceData.value?.texts[previous.value?.files[file.value]])
const after = computed(() => resourceData.value?.texts[current.value?.files[file.value]])
const diff = computed(() => lineDiff(before.value, after.value))
const displayDiff = computed(() => showAllLines.value ? diff.value : compactDiff(diff.value))
const added = computed(() => diff.value.filter(line => line.kind === 'add').length)
const removed = computed(() => diff.value.filter(line => line.kind === 'remove').length)
const beforeMode = computed(() => previous.value?.executable?.[file.value])
const afterMode = computed(() => current.value?.executable?.[file.value])
const mode = (value: unknown) => typeof value === 'boolean' ? value ? 'executable' : 'non-executable' : 'not recorded / file absent'
const pathChanged = (path: string) => previous.value?.files[path] !== current.value?.files[path] || previous.value?.executable?.[path] !== current.value?.executable?.[path]

async function load() {
  error.value = ''
  try {
    const response = await fetch(withBase(props.dataPath))
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const archive = await response.json()
    if (archive.schemaVersion !== 2 || !views[archive.key as keyof typeof views]) throw new Error('Unsupported experiment data')
    const requested = new URLSearchParams(window.location.search).get('agent') || ''
    agentKey.value = Object.hasOwn(archive.agents, requested) ? requested : Object.keys(archive.agents)[0]
    data.value = archive
    const version = new URLSearchParams(window.location.search).get('version')
    if (version) {
      await inspect(version)
      const requestedFile = new URLSearchParams(window.location.search).get('file')
      if (requestedFile && paths.value.includes(requestedFile)) file.value = requestedFile
    }
  } catch (failure) { error.value = failure instanceof Error ? failure.message : 'Could not load the archive' }
}
onMounted(load)
function chooseAgent(key: string) {
  agentKey.value = key
  tab.value = 'selection'
  eventFilter.value = ''
  resourceData.value = null
  resourceError.value = ''
  resourceId.value = ''
  inlineChanges.value = false
  copyText.value = 'Copy resource link'
}
async function inspect(id: string, inline = false) {
  if (!inline) tab.value = 'resources'
  resourceError.value = ''
  resourceId.value = id
  copyText.value = 'Copy resource link'
  fileView.value = 'diff'
  showAllLines.value = false
  const requestedAgent = agentKey.value
  try {
    let archive = resourceCache.get(requestedAgent)
    if (!archive) {
      const response = await fetch(withBase(agent.value.resourcesPath))
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      archive = await response.json()
      resourceCache.set(requestedAgent, archive)
    }
    if (agentKey.value !== requestedAgent) return
    resourceData.value = archive
    const parent = archive.states[id]?.parent
    compareId.value = parent && archive.states[parent] ? parent : archive.initialId
    resetFile()
  } catch (failure) { resourceError.value = failure instanceof Error ? failure.message : 'Could not load resources' }
}
async function openChanges(id: string) {
  selectionScroll = window.scrollY
  inlineChanges.value = true
  await inspect(id, true)
  await nextTick()
  resourcePanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function closeChanges() {
  inlineChanges.value = false
  window.scrollTo({ top: selectionScroll, behavior: 'smooth' })
}
function resetFile() {
  file.value = paths.value.find(pathChanged) || paths.value[0] || ''
}
async function copyLink() {
  const url = new URL(window.location.href)
  url.searchParams.set('agent', agentKey.value)
  url.searchParams.set('version', resourceId.value)
  if (file.value) url.searchParams.set('file', file.value)
  try { await navigator.clipboard.writeText(url.toString()); copyText.value = 'Link copied' }
  catch { window.history.replaceState(null, '', url); copyText.value = 'Link in address bar' }
}
</script>

<template>
  <main class="sx-explorer">
    <header class="sx-heading"><div><a class="sx-eyebrow" :href="withBase('/experiments/')">FlashRSI / Experiment explorer ↗</a><h1>{{ data?.algorithm || 'Experiment' }} <span>×</span> {{ data?.benchmark || 'Benchmark' }}</h1><p>{{ data?.lens || 'Loading recorded selection evidence…' }}</p></div><span class="sx-badge">Historical selection · No test results</span></header>
    <section v-if="error" class="sx-panel" role="alert"><p>{{ error }}</p><button class="sx-button" @click="load">Retry</button></section>
    <p v-else-if="!data" class="sx-empty" role="status">Loading experiment data…</p>
    <template v-else-if="agent">
      <div class="sx-toolbar"><div class="sx-segmented" aria-label="Target harness"><button v-for="(value, key) in data.agents" :key="key" :class="{ active: agentKey === key }" :aria-pressed="agentKey === key" @click="chooseAgent(String(key))">{{ value.label }}</button></div><p>Target <strong>{{ agent.targetModel }}</strong> / Worker <strong>{{ agent.workerModel }}</strong></p></div>
      <section class="sx-rule"><span class="sx-eyebrow">How selection works in this archive</span><p>{{ data.selectionRule }}</p></section>
      <nav class="sx-tabs" aria-label="Experiment views"><button :class="{ active: tab === 'selection' }" @click="tab = 'selection'">{{ data.lens }}</button><button :class="{ active: tab === 'resources' }" @click="inspect(resourceId || agent.selectedId)">Resource comparison</button><button :class="{ active: tab === 'records' }" @click="tab = 'records'">Recorded events <small>{{ agent.events.length }}</small></button></nav>
      <component v-show="tab === 'selection'" :is="methodView" :key="agentKey" :agent="agent" @inspect="openChanges" />
      <section v-if="tab === 'resources' || (tab === 'selection' && inlineChanges)" ref="resourcePanel" class="sx-resources sx-panel">
        <div class="sx-section-title"><div><h2>File changes · {{ short(resourceId) }}</h2><p>Compare this candidate, branch, or selected artifact. Only resource paths changed during the run are listed.</p></div><div class="sx-control-row"><button v-if="tab === 'selection'" class="sx-button" @click="closeChanges">Back to selection</button><button class="sx-button" @click="copyLink">{{ copyText }}</button></div></div>
        <p v-if="resourceError" role="alert">{{ resourceError }}</p><p v-else-if="!resourceData" role="status">Loading resource text…</p>
        <template v-else>
          <div class="sx-compare-controls"><label>Version <select aria-label="Resource version" v-model="resourceId" @change="inspect(resourceId)"><option v-for="(_, id) in resourceData.states" :key="id" :value="id">{{ short(id) }}{{ id === agent.selectedId ? ' · selected artifact' : id === agent.initialId ? ' · seed' : '' }}</option></select></label><label>Compare against <select aria-label="Comparison base" v-model="compareId" @change="resetFile"><option v-for="(_, id) in resourceData.states" :key="id" :value="id">{{ short(id) }}{{ id === agent.initialId ? ' · seed' : '' }}</option></select></label><label>File <select aria-label="Resource file" v-model="file"><option v-for="path in paths" :key="path" :value="path">{{ path }}{{ pathChanged(path) ? ' · changed' : '' }}</option></select></label></div>
          <p v-if="!current" class="sx-empty">No resource files were preserved for this proposed version.</p>
          <template v-else>
            <div class="sx-control-row"><div class="sx-segmented" aria-label="File display"><button v-for="view in ['diff', 'before', 'after', 'side by side']" :key="view" :class="{ active: fileView === view }" @click="fileView = view">{{ view }}</button></div><span class="sx-diff-added">+{{ added }}</span><span class="sx-diff-removed">−{{ removed }}</span><label v-if="fileView === 'diff'"><input v-model="showAllLines" type="checkbox" /> Show unchanged lines</label></div>
            <p class="sx-note">File mode: {{ mode(beforeMode) }} → {{ mode(afterMode) }}. Diff normalizes CRLF line endings; complete text is available in Before / After.</p>
            <p v-if="!added && !removed" class="sx-note">No logical-line changes in this file. File mode or line-ending changes may still differ between versions.</p>
            <div v-if="fileView === 'diff'" class="sx-diff-reader" tabindex="0" aria-label="File diff"><table><tbody><tr v-for="(line, index) in displayDiff" :key="index" :class="line.kind"><td class="sx-diff-number">{{ line.before }}</td><td class="sx-diff-number">{{ line.after }}</td><td class="sx-diff-sign">{{ line.kind === 'add' ? '+' : line.kind === 'remove' ? '−' : line.kind === 'gap' ? '⋯' : ' ' }}</td><td><pre><code>{{ line.text || ' ' }}</code></pre></td></tr></tbody></table></div>
            <div v-else-if="fileView === 'side by side'" class="sx-code-columns"><section><h3>Before · {{ short(compareId) }}</h3><pre tabindex="0"><code>{{ before === undefined ? '(File absent in this version)' : before }}</code></pre></section><section><h3>After · {{ short(resourceId) }}</h3><pre tabindex="0"><code>{{ after === undefined ? '(File absent in this version)' : after }}</code></pre></section></div>
            <pre v-else class="sx-file-full" tabindex="0"><code>{{ fileView === 'before' ? (before === undefined ? '(File absent in this version)' : before) : (after === undefined ? '(File absent in this version)' : after) }}</code></pre>
          </template>
        </template>
      </section>
      <section v-else-if="tab === 'records'" class="sx-records"><div class="sx-section-title"><div><h2>Recorded algorithm events</h2><p>Admission, retention, and final selection are kept as distinct event types.</p></div><label>Filter <input v-model="eventFilter" type="search" placeholder="Type, reason, module, or version…" /></label></div><div class="sx-ledger"><details v-for="(event, index) in events" :key="event.record + index"><summary><code>{{ event.record }}</code><span>{{ event.details.kind || 'record' }}</span><span v-if="event.details.accepted !== undefined" :class="['sx-badge', event.details.accepted ? 'good' : 'muted']">accepted: {{ event.details.accepted }}</span></summary><pre><code>{{ JSON.stringify(event.details, null, 2) }}</code></pre></details><p v-if="!events.length" class="sx-empty">No recorded events match this filter.</p></div><details class="sx-panel"><summary>Non-test evaluation ledger · {{ agent.evaluations.length }} records</summary><div class="sx-table-scroll"><table><thead><tr><th>Record / stage</th><th>Version</th><th>Tasks</th><th>Recorded hard score</th></tr></thead><tbody><tr v-for="(row, index) in agent.evaluations" :key="index"><td>{{ row.record }}</td><td><code>{{ short(row.id) }}</code></td><td>{{ row.tasks }}</td><td>{{ pct(row.score) }}</td></tr></tbody></table></div></details></section>
      <footer class="sx-footer"><span>Historical evidence, not a re-ranking of the experiments.</span><span>Full Worker prompts and Target conversations are not included.</span></footer>
    </template>
  </main>
</template>
