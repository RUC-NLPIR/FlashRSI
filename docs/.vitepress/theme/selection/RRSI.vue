<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, number, short } from './format'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const active = ref(0)
const round = computed(() => props.agent.method.rounds[active.value])
const pp = (value: unknown) => typeof value === 'number' ? `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)} pp` : 'Not measured'
const variants = computed(() => {
  const groups = new Map<number, any[]>()
  for (const edit of round.value.edits) groups.set(edit.variant, [...(groups.get(edit.variant) || []), edit])
  return [...groups].map(([variant, edits]) => ({ variant, edits, first: edits[0], outcome: [...new Set(edits.map(edit => edit.outcome))].join(' / ') }))
})
const smoke = (id: string) => props.agent.method.smokeGates.find((row: any) => row.snapshot_id === id)
</script>
<template>
  <div data-method="rrsi">
    <div class="sx-stats"><div class="sx-stat"><span>Calibrated uncertainty δ</span><strong>{{ (agent.method.calibration.delta * 100).toFixed(3) }} pp</strong><small>{{ agent.method.calibration.source }}</small></div><div class="sx-stat"><span>Recorded rounds</span><strong>{{ agent.method.rounds.length }}</strong><small>Variant competition from a shared incumbent</small></div><div class="sx-stat"><span>Selection split</span><strong>Native train</strong><small>Dev was not used for selection</small></div></div>
    <section class="sx-panel"><h2>Round tournament</h2><p>Several independent edits may belong to one variant. ACCEPTED, LOST, and REJECTED are distinct recorded outcomes; no new ranking is computed here.</p><div class="sx-control-row"><button v-for="(row, index) in agent.method.rounds" :key="row.step" :class="['sx-button', { active: active === index }]" @click="active = Number(index)">Round {{ row.step + 1 }}</button></div><div class="sx-flow"><div><small>Round incumbent</small><strong>{{ pct(round.score) }}</strong><small>Cost {{ number(round.cost) }}</small><code>{{ short(round.incumbent_id) }}</code></div><span>→</span><div><small>Mechanism budget</small><strong>{{ round.budget }} edits</strong><small>{{ round.stalled ? 'Stalled flag set' : 'Stalled flag not set' }}</small></div><span>→</span><div><small>Next incumbent / final artifact</small><strong>{{ short(round.nextIncumbent) }}</strong><button class="sx-button" @click="$emit('inspect', round.nextIncumbent)">View diff ↗</button></div></div>
      <div class="sx-grid two"><div v-for="variant in variants" :key="variant.variant" class="sx-card"><div class="sx-card-top"><h3>Variant {{ variant.variant + 1 }}</h3><span :class="['sx-badge', variant.outcome === 'ACCEPTED' ? 'good' : variant.outcome === 'REJECTED' ? 'bad' : 'muted']">{{ variant.outcome }}</span></div><p>{{ variant.edits.length }} edit record(s) · {{ variant.first.admissible ? 'Admissible' : 'Not admissible' }}</p><div class="sx-grid two"><div><h4>Measured score Δ</h4>{{ pp(variant.first.delta_S) }}</div><div><h4>Relative cost Δ</h4>{{ typeof variant.first.delta_C === 'number' ? pct(variant.first.delta_C) : 'Not measured' }}</div></div><p>{{ variant.first.reason || 'No aggregate reason preserved' }}</p><p v-if="smoke(variant.first.candidate_id)" class="sx-note">Smoke gate: {{ smoke(variant.first.candidate_id).passed ? 'passed' : 'failed' }}</p><details v-for="(edit, index) in variant.edits" :key="index"><summary>{{ edit.id || `Edit ${index + 1}` }} · {{ edit.component || 'Unspecified mechanism' }}</summary><p>{{ edit.hypothesis || edit.reason }}</p><p class="sx-note">{{ (edit.paths || []).join(', ') }}</p><pre v-if="edit.guards">{{ JSON.stringify(edit.guards, null, 2) }}</pre></details><button v-if="variant.first.candidate_id" class="sx-button" @click="$emit('inspect', variant.first.candidate_id)">Variant diff ↗</button></div></div>
    </section><section class="sx-panel"><h3>Recorded selection parameters</h3><p class="sx-note">Measured cost stays in the native recorded units. Post-selection dev diagnostics are not used to choose winners in this view.</p><pre>{{ JSON.stringify(agent.method.parameters, null, 2) }}</pre><h3 style="margin-top:20px">Final native incumbent</h3><p>Recorded score {{ pct(agent.method.promotion.score) }} · cost {{ number(agent.method.promotion.cost) }}</p><button class="sx-button" @click="$emit('inspect', agent.selectedId)">View selected artifact diff ↗</button></section>
  </div>
</template>
