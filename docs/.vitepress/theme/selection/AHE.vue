<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, size } from './format'
import FinalSelection from './FinalSelection.vue'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const active = ref(0)
const repair = computed(() => props.agent.method.repairs[active.value])
const text = (value: any) => typeof value === 'string' ? value : JSON.stringify(value, null, 2)
</script>
<template>
  <div data-method="ahe">
    <section class="sx-panel"><h2>Diagnose → edit → file audit</h2><p>Training score changes alone do not explain a retention decision. Inspect the predicted fixes, realized risks, and recorded file verdicts.</p><div class="sx-control-row"><button v-for="(row, index) in agent.method.repairs" :key="row.step" :class="['sx-button', { active: active === index }]" @click="active = index">Repair {{ row.step + 1 }}</button></div><div class="sx-flow"><div><small>Parent training score</small><strong>{{ pct(repair.parent_score) }}</strong></div><span>→</span><div><small>Candidate training score</small><strong>{{ pct(repair.candidate_score) }}</strong></div><span>→</span><div><small>Recorded decision</small><strong>{{ repair.kind }} · {{ repair.accepted ? 'retained' : 'not retained' }}</strong></div></div><div class="sx-grid two"><div class="sx-card"><h4>Root cause</h4><p class="sx-prose">{{ text(repair.manifest?.root_cause) }}</p></div><div class="sx-card"><h4>Targeted fix</h4><p class="sx-prose">{{ text(repair.manifest?.targeted_fix) }}</p></div></div><div class="sx-table-scroll" style="margin-top:18px"><table><thead><tr><th>Changed file</th><th>Predicted / realized fixes</th><th>Predicted / realized risks</th><th>File audit verdict</th></tr></thead><tbody><tr v-for="row in repair.changes" :key="row.path"><td>{{ row.path }}</td><td>{{ size(row.predicted_fixes) }} / {{ size(row.actually_fixed) }}<br><small>{{ size(row.still_failed) }} still failed</small></td><td>{{ size(row.predicted_risks) }} / {{ size(row.risk_realized) }}</td><td><span class="sx-badge">{{ row.verdict.replaceAll('_', ' ') }}</span><details><summary>Task-level evidence</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details></td></tr></tbody></table></div><p class="sx-note">{{ size(repair.unattributed_regressions) }} unattributed training regressions were recorded. A retained edit is not necessarily the final selected version.</p><button class="sx-button" @click="$emit('inspect', repair.node.id)">View retained candidate diff ↗</button></section>
    <FinalSelection :rows="agent.method.selection" title="Separate final dev selection" @inspect="$emit('inspect', $event)" />
  </div>
</template>
