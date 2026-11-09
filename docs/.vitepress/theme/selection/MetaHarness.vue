<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, short } from './format'
import FinalSelection from './FinalSelection.vue'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const active = ref(0)
const trial = computed(() => props.agent.method.trials[active.value])
</script>
<template>
  <div data-method="meta_harness">
    <div class="sx-stats"><div class="sx-stat"><span>Recorded experiments</span><strong>{{ agent.method.trials.length }}</strong><small>Training history, not a dev hill climb</small></div><div class="sx-stat"><span>Final dev entries</span><strong>{{ agent.method.selection.length }}</strong><small>Archived versions scored after search</small></div><div class="sx-stat"><span>Initial training score</span><strong>{{ pct(agent.method.initialTrain) }}</strong><small>Kept distinct from the dev scores below</small></div></div>
    <section class="sx-panel"><h2>Experiment notebook</h2><p>Browse an experiment alongside the earlier recorded training history. Earlier rows are historical context; they are not a claim about which files the Worker actually opened.</p><div class="sx-control-row"><label>Experiment<select v-model="active"><option v-for="(row, index) in agent.method.trials" :key="row.step" :value="index">Experiment {{ row.step + 1 }} · {{ pct(row.score) }} train</option></select></label><button class="sx-button" @click="$emit('inspect', trial.node.id)">View experiment diff ↗</button></div><div class="sx-flow"><div><small>Recorded base version</small><strong>{{ short(trial.parent) }}</strong></div><span>→</span><div><small>Training score</small><strong>{{ pct(trial.score) }}</strong></div><span>→</span><div><small>Versions recorded earlier</small><strong>{{ active }}</strong></div></div><details v-if="trial.workerNoteExcerpt" open><summary>Recorded Worker reply excerpt</summary><pre>{{ trial.workerNoteExcerpt }}</pre></details><details><summary>Earlier notebook entries · {{ active }}</summary><div class="sx-table-scroll"><table><thead><tr><th>Experiment</th><th>Train score</th><th>Version</th></tr></thead><tbody><tr v-for="row in agent.method.trials.slice(0, active)" :key="row.step"><td>{{ row.step + 1 }}</td><td>{{ pct(row.score) }}</td><td>{{ short(row.node.id) }}</td></tr></tbody></table></div></details></section>
    <FinalSelection :rows="agent.method.selection" title="Training search → separate final dev selection" @inspect="$emit('inspect', $event)" />
  </div>
</template>
