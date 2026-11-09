<script setup lang="ts">
import { pct, short, selectedLabel } from './format'
defineProps<{ rows: any[]; title?: string; scoreLabel?: string }>()
defineEmits<{ inspect: [id: string] }>()
</script>

<template>
  <section class="sx-panel sx-final-selection">
    <h3>{{ title || 'Recorded final dev selection' }}</h3>
    <p class="sx-note">This phase is separate from search admission. Markers follow the recorded artifact; this page does not reselect a winner.</p>
    <div class="sx-table-scroll"><table><thead><tr><th>Version</th><th>{{ scoreLabel || 'Dev score' }}</th><th>Final selection</th><th></th></tr></thead><tbody><tr v-for="(row, index) in rows" :key="row.id + index" :class="{ 'sx-selected-row': row.selected || row.finalContent }"><td>{{ index === 0 ? 'Seed / first entry' : `Entry ${index}` }} <code>{{ short(row.id) }}</code></td><td>{{ pct(row.score) }}</td><td><span v-if="selectedLabel(row)" class="sx-badge good">{{ selectedLabel(row) }}</span><span v-else class="sx-muted">Not selected</span></td><td><button class="sx-button" @click="$emit('inspect', row.id)">View diff ↗</button></td></tr></tbody></table></div>
    <p v-if="!rows.length" class="sx-note">No final selection table was preserved in these records.</p>
  </section>
</template>
