<script setup lang="ts">
import { computed, ref } from 'vue'
import { pct, short, selectedLabel } from './format'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const generation = ref(0)
const current = computed(() => props.agent.method.generations[generation.value])
</script>
<template>
  <div data-method="evoprompt">
    <div class="sx-stats"><div class="sx-stat"><span>Archived variant</span><strong>DE</strong><small>Positional trial-versus-target replacement</small></div><div class="sx-stat"><span>Population slots</span><strong>{{ current.slots.length }}</strong><small>Each slot retains its own winner</small></div><div class="sx-stat"><span>Scoring</span><strong>Dev</strong><small>{{ agent.method.optimizationTasks }} tasks per candidate</small></div></div>
    <section class="sx-panel"><h2>Population arena</h2><p>Changing one slot is different from replacing the whole population leader. A tied trial keeps the target in these records.</p><div class="sx-control-row"><button v-for="(row, index) in agent.method.generations" :key="row.step" :class="['sx-button', { active: generation === index }]" @click="generation = index">Generation {{ row.step + 1 }}</button></div><div class="sx-table-scroll"><table><thead><tr><th>Slot</th><th>Target</th><th>Trial</th><th>Recorded survivor</th><th>Replacement</th><th></th></tr></thead><tbody><tr v-for="row in current.slots" :key="row.slot"><td>{{ row.slot }}</td><td>{{ pct(row.target.score) }}<code>{{ short(row.target.id) }}</code></td><td>{{ pct(row.trial.score) }}<code>{{ short(row.trial.id) }}</code></td><td>{{ pct(row.survivor.score) }}<code>{{ short(row.survivor.id) }}</code></td><td><span :class="['sx-badge', row.replaced ? 'good' : 'muted']">{{ row.replaced ? 'Trial replaces target' : row.trial.score === row.target.score ? 'Tie · target retained' : 'Target retained' }}</span></td><td><button class="sx-button" @click="$emit('inspect', row.trial.id)">Trial diff ↗</button></td></tr></tbody></table></div></section>
    <section class="sx-panel"><h3>Final population → promoted prompt</h3><p class="sx-note">The final promotion is distinct from the five generations of slot-level survival.</p><div class="sx-grid"><div v-for="(row, index) in agent.method.finalPopulation" :key="row.id + index" :class="['sx-card', { active: row.finalContent }]"><div class="sx-card-top"><h4>Slot {{ index + 1 }}</h4><strong>{{ pct(row.score) }}</strong></div><span v-if="selectedLabel(row)" class="sx-badge good">{{ selectedLabel(row) }}</span><button class="sx-button" @click="$emit('inspect', row.id)">Prompt diff ↗</button></div></div></section>
  </div>
</template>
