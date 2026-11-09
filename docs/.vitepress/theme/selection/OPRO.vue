<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, selectedLabel } from './format'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const ranked = ref(false)
const selected = ref(0)
const history = computed(() => ranked.value ? [...props.agent.method.history].sort((a, b) => b.score - a.score || a.number - b.number) : props.agent.method.history)
const prompt = computed(() => props.agent.method.history[selected.value])
</script>
<template>
  <div data-method="opro">
    <div class="sx-stats"><div class="sx-stat"><span>Optimization history</span><strong>{{ agent.method.history.length }}</strong><small>Seed + proposed prompts</small></div><div class="sx-stat"><span>Optimization split</span><strong>Train</strong><small>{{ agent.method.optimizationTasks }} tasks per evaluation</small></div><div class="sx-stat"><span>Proposal base</span><strong>Fixed seed</strong><small>History does not move the active harness</small></div></div>
    <section class="sx-panel"><div class="sx-section-title"><div><h2>Scored prompt history</h2><p>A later prompt may score worse and still enter the history supplied to the optimizer.</p></div><label><input v-model="ranked" type="checkbox" /> Rank by optimization score</label></div><div class="sx-table-scroll"><table><thead><tr><th>Proposal</th><th>Train score</th><th>Historical outcome</th><th></th></tr></thead><tbody><tr v-for="row in history" :key="row.id" :class="{ 'sx-selected-row': row.finalContent }"><td><button class="sx-row-button" @click="selected = row.number">{{ row.number ? `Prompt ${row.number}` : 'Seed prompt' }}</button></td><td>{{ pct(row.score) }}</td><td><span v-if="selectedLabel(row)" class="sx-badge good">{{ selectedLabel(row) }}</span><span v-else class="sx-muted">Retained in history</span></td><td><button class="sx-button" @click="$emit('inspect', row.id)">View diff ↗</button></td></tr></tbody></table></div></section>
    <section class="sx-panel"><h3>{{ prompt.number ? `Prompt ${prompt.number}` : 'Seed prompt' }} · {{ pct(prompt.score) }}</h3><p class="sx-note">The complete instruction text recorded for this history entry.</p><pre tabindex="0"><code>{{ prompt.text }}</code></pre></section>
  </div>
</template>
