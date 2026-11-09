<script setup lang="ts">
import { computed, ref } from 'vue'
import { number } from './format'
import FinalSelection from './FinalSelection.vue'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const cursor = ref(0)
const update = computed(() => props.agent.method.updates[cursor.value])
const maxChars = computed(() => Math.max(...props.agent.method.updates.map((row: any) => row.changedTextChars)))
</script>
<template>
  <div data-method="ace">
    <div class="sx-stats"><div class="sx-stat"><span>Curator advances</span><strong>{{ agent.method.updates.length }}</strong><small>Playbook updates, not dev wins</small></div><div class="sx-stat"><span>Validation checkpoints</span><strong>{{ agent.method.checkpoints.length }}</strong><small>Separate from per-example curation</small></div><div class="sx-stat"><span>Declined records</span><strong>{{ agent.method.declined }}</strong><small>Preserved without invented scores</small></div></div>
    <section class="sx-panel"><h2>Playbook growth ledger</h2><p>Move through the recorded curator updates. Text size describes the resource, not accuracy or confidence.</p><div class="sx-table-scroll"><svg width="1000" height="140" role="img" aria-label="Changed playbook text size over curator updates"><rect v-for="row in agent.method.updates" :key="row.number" :x="row.number / agent.method.updates.length * 990" :y="125 - row.changedTextChars / maxChars * 110" :width="Math.max(1, 990 / agent.method.updates.length - .4)" :height="row.changedTextChars / maxChars * 110" fill="#b65b3b" opacity=".65"><title>Update {{ row.number }} · {{ number(row.changedTextChars) }} text characters</title></rect></svg></div><div class="sx-control-row"><label>Curator update <input v-model.number="cursor" type="number" :min="0" :max="agent.method.updates.length - 1" @change="cursor = Math.max(0, Math.min(agent.method.updates.length - 1, cursor || 0))" /></label><input v-model.number="cursor" type="range" :min="0" :max="agent.method.updates.length - 1" aria-label="Curator update position" /></div><div v-if="update" class="sx-callout"><h3>Update {{ update.number }}</h3><p>Changed resource: {{ update.paths.join(', ') }}</p><p>{{ number(update.changedTextChars) }} characters in the changed text.</p><button class="sx-button" @click="$emit('inspect', update.id)">Compare this playbook update ↗</button></div><p class="sx-note">No per-curation dev score is assigned here. The archived validation checkpoints below are the available selection evidence.</p></section>
    <FinalSelection :rows="agent.method.checkpoints" title="Periodic validation → checkpoint promotion" score-label="Validation score" @inspect="$emit('inspect', $event)" />
  </div>
</template>
