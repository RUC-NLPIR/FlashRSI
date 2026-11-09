<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, selectedLabel } from './format'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const active = ref(0)
const draft = ref(-1)
const design = computed(() => props.agent.method.archive[active.value])
const ranked = computed(() => [...props.agent.method.archive].sort((a, b) => b.score - a.score || a.number - b.number))
</script>
<template>
  <div data-method="adas">
    <div class="sx-stats"><div class="sx-stat"><span>Design archive</span><strong>{{ agent.method.archive.length }}</strong><small>Includes the initial harness</small></div><div class="sx-stat"><span>Admission</span><strong>Archive entry</strong><small>Does not mean a new incumbent</small></div><div class="sx-stat"><span>Final decision</span><strong>Dev fitness</strong><small>Recorded selection, not a new ranking run</small></div></div>
    <section class="sx-panel"><h2>Archive of evaluated designs</h2><p>Names below are display labels. The historical archive preserved design accounts and scores, rather than the newer name/thought/fitness schema.</p><div class="sx-grid"><button v-for="row in ranked" :key="row.id" :class="['sx-card sx-row-button', { active: active === row.number }]" @click="active = row.number; draft = -1"><div class="sx-card-top"><h4>{{ row.number ? `Design ${row.number}` : 'Initial design' }}</h4><strong>{{ pct(row.score) }}</strong></div><span v-if="selectedLabel(row)" class="sx-badge good">{{ selectedLabel(row) }}</span><span v-else class="sx-badge">Archived · not selected</span><p>{{ row.account.slice(0, 170) }}{{ row.account.length > 170 ? '…' : '' }}</p></button></div></section>
    <section class="sx-panel"><div class="sx-section-title"><div><h2>{{ design.number ? `Design ${design.number}` : 'Initial design' }}</h2><p>Full recorded design account · {{ pct(design.score) }}</p></div><button class="sx-button" @click="$emit('inspect', design.id)">View design diff ↗</button></div><p class="sx-prose">{{ design.account }}</p><template v-if="design.revisions?.length"><h3>Recorded design revisions before evaluation</h3><div class="sx-control-row"><button v-for="(_, index) in design.revisions" :key="index" :class="['sx-button', { active: draft === index }]" @click="draft = Number(index)">Draft {{ Number(index) + 1 }}</button></div><p v-if="draft >= 0" class="sx-callout sx-prose">{{ design.revisions[draft] }}</p></template></section>
  </div>
</template>
