<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, short, number } from './format'
import FinalSelection from './FinalSelection.vue'

const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const method = computed(() => props.agent.evolution)
const key = computed(() => method.value.key)
const active = ref(0)
const filter = ref('all')
const module = ref('all')
const rows = computed(() => {
  const e = method.value
  let result = key.value === 'opro' ? e.history : key.value === 'gepa' ? e.population : key.value === 'ace' ? e.playbooks : key.value === 'adas' ? e.designs : key.value === 'rrsi' ? e.edits : key.value === 'evoharness' ? e.operations : e.entries
  if (filter.value !== 'all') result = result.filter((r: any) => r.kind === filter.value || r.level === filter.value || r.outcome === filter.value)
  if (module.value !== 'all') result = result.filter((r: any) => r.module === module.value)
  return result
})
const item = computed(() => rows.value[active.value] || rows.value[0])
const outcome = (r: any) => r.outcome || (r.kind === 'upper_bound_pruned' ? 'Upper bound pruned' : r.kind === 'admit' ? r.accepted ? 'Admitted' : 'Not admitted' : r.accepted === true ? 'Accepted' : r.accepted === false ? 'Not accepted' : r.kind || 'Recorded')
const delta = (value: unknown) => typeof value === 'number' ? `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)} pp` : 'Not recorded'
const version = (r: any) => r.candidate_id || r.snapshot_id || r.id
const hasResource = (id: string) => props.agent.preservedVersions.includes(id)
const score = (r: any) => r.candidate_score ?? r.score
const labels: Record<string, string> = {
  skillopt: 'Fast / slow skill decisions', opro: 'Scored prompt history', evoprompt: 'Population arena',
  gepa: 'Population coverage and ancestry', ace: 'Playbook update ledger', ahe: 'Repair audit',
  adas: 'Evaluated design archive', meta_harness: 'Experiment notebook', darwinx: 'Branch admission gates',
  modular_rsi: 'Module branches and integration', rrsi: 'Round tournament', evoharness: 'Skill production',
}
const modes = computed(() => [...new Set((key.value === 'rrsi' ? method.value.edits : key.value === 'evoharness' ? method.value.operations : method.value.entries).map((r: any) => r.outcome || r.level || r.kind).filter(Boolean))] as string[])
</script>

<template>
  <div :data-method="key" class="terminal-evolution">
    <div class="sx-stats"><div class="sx-stat"><span>Algorithm records</span><strong>{{ agent.events.length }}</strong></div><div class="sx-stat"><span>Changed resource paths</span><strong>{{ agent.changedPaths.length }}</strong></div><div class="sx-stat"><span>Selected artifact</span><strong>{{ short(agent.selectedId) }}</strong><button class="sx-button" @click="$emit('inspect', agent.selectedId)">View selected diff ↗</button></div></div>

    <section v-if="key === 'evoprompt'" class="sx-panel">
      <h2>Population arena</h2>
      <div class="sx-control-row"><button v-for="(generation, index) in method.generations" :key="index" :class="['sx-button', { active: active === index }]" @click="active = Number(index)">Generation {{ (generation.step ?? index) + 1 }}</button></div>
      <template v-if="method.generations[active]">
        <h3>{{ method.generations[active].variant || 'Population' }}</h3>
        <div class="sx-grid"><div v-for="(r, index) in method.generations[active].population" :key="index" :class="['sx-card', { active: r.snapshot_id === agent.selectedId }]"><h4>Surviving slot {{ Number(index) + 1 }}</h4><p>{{ pct(r.score) }}</p><code>{{ short(r.snapshot_id) }}</code><button class="sx-button" @click="$emit('inspect', r.snapshot_id)">Survivor diff ↗</button></div></div>
        <div class="sx-table-scroll" style="margin-top:16px"><table><thead><tr><th>Trial</th><th>Score</th><th>Recorded slot survivor</th><th></th></tr></thead><tbody><tr v-for="(trial, index) in method.generations[active].proposals" :key="index"><td>{{ Number(index) + 1 }} · {{ short(trial.snapshot_id) }}</td><td>{{ pct(trial.score) }}</td><td>{{ short(method.generations[active].population[index]?.snapshot_id) }}</td><td><button class="sx-button" @click="$emit('inspect', trial.snapshot_id)">Trial diff ↗</button></td></tr></tbody></table></div>
        <details style="margin-top:16px"><summary>Recorded proposals and replacement evidence</summary><pre>{{ JSON.stringify(method.generations[active].proposals, null, 2) }}</pre></details>
      </template>
    </section>

    <section v-if="key === 'gepa'" class="sx-panel"><h2>Task-winner coverage</h2><p>Highlighted cells are co-best within the recorded population, including ties.</p><div class="sx-table-scroll"><svg :width="Math.max(240, (method.population[0]?.coverage.length || 0) * 22 + 60)" :height="method.population.length * 24 + 20" role="img" aria-label="Population task coverage"><g v-for="(r, index) in method.population" :key="index" :transform="`translate(0,${index * 24 + 8})`"><text x="0" y="15" fill="currentColor" font-size="12">P{{ r.index }}</text><rect v-for="(covered, task) in r.coverage" :key="task" :x="50 + Number(task) * 22" y="0" width="19" height="20" :fill="covered ? '#b65b3b' : '#9da6ae'" :opacity="covered ? 1 : .2"><title>P{{ r.index }} · task {{ Number(task) + 1 }} · {{ covered ? 'co-best' : 'below best' }}</title></rect></g></svg></div></section>

    <section v-if="key === 'modular_rsi'" class="sx-panel"><h2>Module branches → integration</h2><div class="sx-grid"><button v-for="branch in method.modules" :key="branch.name" :class="['sx-card sx-row-button', { active: module === branch.name }]" @click="module = branch.name; active = 0"><h3>{{ branch.name }}</h3><p>{{ branch.entries.length }} branch decisions</p></button><button class="sx-card sx-row-button" @click="module = 'integration'; active = 0"><h3>Integration</h3><p>Recorded merge decisions</p></button></div><button class="sx-button" style="margin-top:12px" @click="module = 'all'">Show all branches</button><details style="margin-top:16px"><summary>Review and execution gates · {{ method.gates.length }}</summary><pre>{{ JSON.stringify(method.gates, null, 2) }}</pre></details></section>

    <section v-if="key === 'rrsi'" class="sx-panel"><h2>Round contexts</h2><div class="sx-grid"><div v-for="(round, index) in method.contexts" :key="index" class="sx-card"><h3>Round {{ (round.step ?? round.t ?? index) + 1 }}</h3><p>Incumbent {{ short(round.incumbent_id) }} · score {{ pct(round.score) }} · cost {{ number(round.cost) }}</p><p>Budget {{ round.budget ?? 'Not recorded' }} · {{ round.stalled ? 'stalled' : 'active' }}</p><details><summary>Incumbent and mechanism budget</summary><pre>{{ JSON.stringify(round, null, 2) }}</pre></details></div></div><details style="margin-top:16px"><summary>Calibrated uncertainty</summary><pre>{{ JSON.stringify(method.calibration, null, 2) }}</pre></details></section>

    <section v-if="key !== 'evoprompt'" class="sx-panel">
      <div class="sx-section-title"><h2>{{ labels[key] }}</h2><label v-if="['skillopt', 'rrsi', 'evoharness', 'darwinx'].includes(key)">Filter<select v-model="filter" @change="active = 0"><option value="all">All records</option><option v-for="mode in modes" :key="mode" :value="mode">{{ mode }}</option></select></label></div>
      <div class="sx-table-scroll"><table><thead><tr><th>{{ key === 'opro' ? 'Prompt' : key === 'gepa' ? 'Member' : key === 'ace' ? 'Playbook' : key === 'adas' ? 'Design' : 'Step' }}</th><th v-if="key === 'skillopt'">Fast / slow</th><th v-if="key === 'gepa'">Parents / co-best tasks</th><th v-if="key === 'darwinx'">Fidelity / samples</th><th v-if="key === 'darwinx'">Gain / regression mass</th><th v-if="key === 'modular_rsi'">Module</th><th v-if="key === 'modular_rsi'">Decision</th><th v-if="key === 'rrsi'">Variant / admissibility</th><th v-if="key === 'rrsi'">Mechanism / paths</th><th v-if="key === 'rrsi'">Score Δ / relative cost Δ</th><th v-else-if="key !== 'ace' && key !== 'evoharness' && key !== 'modular_rsi'">{{ key === 'opro' || key === 'meta_harness' ? 'Train score' : key === 'gepa' ? 'Dev mean' : 'Recorded score' }}</th><th v-if="key === 'evoharness'">Level / paths</th><th>Outcome</th><th>Version</th><th></th></tr></thead><tbody><tr v-for="(r, index) in rows" :key="index" :class="{ 'sx-selected-row': version(r) === agent.selectedId }"><td><button class="sx-row-button" @click="active = Number(index)">{{ r.number ?? r.index ?? r.step ?? r.t ?? Number(index) + 1 }}</button></td><td v-if="key === 'skillopt'">{{ r.kind }}</td><td v-if="key === 'gepa'">{{ r.parents.join(' + ') || 'Seed' }} / {{ r.coverage.filter(Boolean).length }}</td><td v-if="key === 'darwinx'">{{ r.fidelity }} / {{ r.samples }}</td><td v-if="key === 'darwinx'">{{ number(r.gain) }} / {{ number(r.regression_mass) }}</td><td v-if="key === 'modular_rsi'">{{ r.module }}</td><td v-if="key === 'modular_rsi'">{{ r.kind }}</td><td v-if="key === 'rrsi'">{{ r.variant }} / {{ r.admissible ? 'Admissible' : 'Not admissible' }}</td><td v-if="key === 'rrsi'">{{ r.component }}<br><small>{{ (r.paths || []).join(', ') }}</small></td><td v-if="key === 'rrsi'">{{ delta(r.delta_S) }} / {{ pct(r.delta_C) }}</td><td v-else-if="key !== 'ace' && key !== 'evoharness' && key !== 'modular_rsi'">{{ pct(score(r)) }}<small v-if="r.parent_score !== undefined"> · parent {{ pct(r.parent_score) }}</small></td><td v-if="key === 'evoharness'">{{ r.level || r.compile_level || r.kind }}<br>{{ (r.changed_paths || []).join(', ') }}</td><td><span :class="['sx-badge', r.accepted === true ? 'good' : 'muted']">{{ outcome(r) }}</span></td><td><code>{{ short(version(r)) }}</code></td><td><button v-if="version(r) && hasResource(version(r))" class="sx-button" @click="$emit('inspect', version(r))">View diff ↗</button><span v-else-if="version(r)" class="sx-note">Resource text not archived</span></td></tr></tbody></table></div>
      <p v-if="!rows.length" class="sx-note">No matching decision rows.</p>
      <div v-if="item" class="sx-card" style="margin-top:18px"><h3>{{ item.kind || labels[key] }} · {{ short(version(item)) }}</h3><p v-if="item.account || item.explanation || item.reason || item.hypothesis" class="sx-prose">{{ item.account || item.explanation || item.reason || item.hypothesis }}</p><pre v-if="key === 'opro' || key === 'gepa'"><code>{{ item.text }}</code></pre><template v-if="key === 'ahe'"><div class="sx-grid two"><div><h4>Root cause</h4><p>{{ item.manifest?.root_cause }}</p></div><div><h4>Targeted fix</h4><p>{{ item.manifest?.targeted_fix }}</p></div></div><div class="sx-table-scroll"><table><thead><tr><th>File</th><th>Predicted fixes</th><th>Realized fixes</th><th>Verdict</th></tr></thead><tbody><tr v-for="change in item.changes" :key="change.path"><td>{{ change.path }}</td><td>{{ change.predicted_fixes?.length }}</td><td>{{ change.actually_fixed?.length }}</td><td>{{ change.verdict }}</td></tr></tbody></table></div></template><details><summary>Recorded decision evidence</summary><pre>{{ JSON.stringify(item, null, 2) }}</pre></details></div>
    </section>
    <section v-if="method.gates.length && key === 'darwinx'" class="sx-panel"><h3>Final admission gates</h3><div class="sx-table-scroll"><table><thead><tr><th>Version</th><th>Gain / regression mass</th><th>Budget δ</th><th>Admitted</th></tr></thead><tbody><tr v-for="(gate, index) in method.gates" :key="index"><td>{{ short(gate.snapshot_id) }}</td><td>{{ number(gate.gain) }} / {{ number(gate.regression_mass) }}</td><td>{{ number(gate.delta) }}</td><td>{{ gate.accepted }}</td></tr></tbody></table></div></section>
    <FinalSelection v-if="method.finalSelection.length" :rows="method.finalSelection" title="Recorded final selection" :score-label="method.finalLabel" @inspect="$emit('inspect', $event)" />
    <FinalSelection v-if="key === 'ace' && method.checkpoints.length" :rows="method.checkpoints" title="Validation checkpoints" score-label="Validation reward" @inspect="$emit('inspect', $event)" />
    <section class="sx-panel"><h3>Selected artifact</h3><p><code>{{ agent.selectedId }}</code></p><button class="sx-button" @click="$emit('inspect', agent.selectedId)">View final file changes ↗</button><details style="margin-top:16px"><summary>Recorded final decision</summary><pre>{{ JSON.stringify(method.promotion, null, 2) }}</pre></details></section>
  </div>
</template>
