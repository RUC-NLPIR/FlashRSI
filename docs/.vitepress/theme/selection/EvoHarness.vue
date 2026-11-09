<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, number } from './format'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const level = ref('all')
const operations = computed(() => props.agent.method.operations.filter((row: any) => level.value === 'all' || row.level === level.value))
const status = (row: any) => row.problem ? 'Declined' : row.accepted ? 'Applied' : row.accepted === false ? 'No content change / not applied' : row.kind
</script>
<template>
  <div data-method="evoharness">
    <div class="sx-stats"><div class="sx-stat"><span>Training stream</span><strong>{{ agent.method.terminal.online_tasks }}</strong><small>Tasks observed online</small></div><div class="sx-stat"><span>Online training score</span><strong>{{ pct(agent.method.terminal.online_score) }}</strong><small>Cumulative stream score, not dev selection</small></div><div class="sx-stat"><span>Terminal skill library</span><strong>{{ agent.method.library.length }}</strong><small>Topic / general reusable resources</small></div></div>
    <div class="sx-flow"><div><small>Experience</small><strong>Task feedback</strong><small>Batch size {{ agent.method.batchSize }}</small></div><span>→</span><div><small>Compilation</small><strong>Topic skills</strong><small>Concrete reusable procedures</small></div><span>→</span><div><small>Generalization</small><strong>General skills</strong><small>Broader reusable guidance</small></div><span>→</span><div><small>Selected artifact</small><strong>Terminal library</strong><small>No best-dev checkpoint</small></div></div>
    <section class="sx-panel"><div class="sx-section-title"><div><h2>Skill production and admission</h2><p>Library updates, declined edits, and no-op proposals remain separate. An applied skill is not a dev-score win.</p></div><label>Level<select v-model="level"><option value="all">All recorded levels</option><option value="topic">Topic</option><option value="general">General</option></select></label></div><div class="sx-table-scroll"><table><thead><tr><th>Step</th><th>Stage / level</th><th>Outcome</th><th>Resource change / reason</th><th></th></tr></thead><tbody><tr v-for="(row, index) in operations" :key="index"><td>{{ row.step }}</td><td>{{ row.kind }}<br>{{ row.level || 'Not classified' }}</td><td><span :class="['sx-badge', row.accepted ? 'good' : row.problem ? 'bad' : 'muted']">{{ status(row) }}</span></td><td>{{ row.problem || (row.changed_paths || []).join(', ') || 'No paths changed' }}</td><td><button v-if="row.candidate_id" class="sx-button" @click="$emit('inspect', row.candidate_id)">View diff ↗</button></td></tr></tbody></table></div></section>
    <section class="sx-panel"><h3>Selected terminal library</h3><p class="sx-note">Levels follow the recorded operation that last changed each path; unclassified seed files are not assigned an invented level.</p><div class="sx-grid"><div v-for="row in agent.method.library" :key="row.path" class="sx-card"><span class="sx-badge">{{ row.level }}</span><h4 style="margin-top:12px;overflow-wrap:anywhere">{{ row.path }}</h4><p>{{ number(row.chars) }} text characters</p><button class="sx-button" @click="$emit('inspect', agent.selectedId)">View final library changes ↗</button></div></div></section>
  </div>
</template>
