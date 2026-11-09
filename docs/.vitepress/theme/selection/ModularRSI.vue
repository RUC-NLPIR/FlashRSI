<script setup lang="ts">
import { computed, ref } from 'vue'
import { short } from './format'
import FinalSelection from './FinalSelection.vue'
const props = defineProps<{ agent: any }>()
defineEmits<{ inspect: [id: string] }>()
const active = ref(0)
const branch = computed(() => props.agent.method.branches[active.value])
const review = (id: string) => props.agent.method.reviews.find((row: any) => row.candidate_id === id)
const gate = (id: string) => id ? props.agent.method.gates.find((row: any) => row.snapshot_id === id || row.candidate_id === id) : undefined
</script>
<template>
  <div data-method="modular_rsi">
    <section class="sx-panel"><h2>Independent module branches</h2><p>These are the modules actually recorded in this historical run, not the framework's current module configuration.</p><div class="sx-grid"><button v-for="(row, index) in agent.method.branches" :key="row.name" :class="['sx-card sx-row-button', { active: active === index }]" @click="active = Number(index)"><h4>{{ row.name.replaceAll('_', ' ') }}</h4><p>{{ row.events.filter((event: any) => event.kind === 'admit').length }} admitted / {{ row.events.filter((event: any) => event.kind === 'decline').length }} declined</p><code>{{ short(row.version) }}</code></button></div><div class="sx-callout"><h3>{{ branch.name.replaceAll('_', ' ') }}</h3><button class="sx-button" @click="$emit('inspect', branch.version)">View branch diff ↗</button><details v-for="(event, index) in branch.events" :key="index"><summary>{{ index + 1 }}. {{ event.kind }} · {{ event.problem || short(event.candidate_id) }}</summary><p>{{ event.problem || event.reason || 'Recorded branch admission' }}</p><template v-if="review(event.candidate_id)"><h4>Worker diff review</h4><p>{{ review(event.candidate_id).accept ? 'Accepted' : 'Declined' }} · {{ review(event.candidate_id).reason }}</p></template><p v-if="gate(event.candidate_id)">Execution gate: {{ gate(event.candidate_id).passed ? 'passed' : 'failed' }}</p><button v-if="event.candidate_id" class="sx-button" @click="$emit('inspect', event.candidate_id)">Candidate diff ↗</button></details></div></section>
    <div class="sx-flow"><div><small>Independent branches</small><strong>{{ agent.method.branches.length }} native mappings</strong></div><span>→</span><div><small>Integration</small><strong>{{ agent.method.integration.length }} recorded attempts</strong></div><span>→</span><div><small>Final dev selection</small><strong>{{ agent.method.selection.length }} entries</strong></div></div>
    <section class="sx-panel"><h3>Integration admission</h3><p>Review and execution gates determine whether integration advances. A completed execution is not proof of a correct answer.</p><div class="sx-table-scroll"><table><thead><tr><th>Attempt</th><th>Decision</th><th>Review / execution</th><th>Recorded reason</th><th></th></tr></thead><tbody><tr v-for="(row, index) in agent.method.integration" :key="index"><td>{{ index + 1 }}</td><td><span :class="['sx-badge', row.kind === 'admit' ? 'good' : 'muted']">{{ row.kind }}</span></td><td>{{ review(row.candidate_id) ? (review(row.candidate_id).accept ? 'Review passed' : 'Review declined') : 'Review not recorded' }}<br>{{ gate(row.candidate_id) ? (gate(row.candidate_id).passed ? 'Execution passed' : 'Execution failed') : 'Execution not recorded' }}</td><td>{{ row.problem || row.reason || 'Admission recorded' }}</td><td><button v-if="row.candidate_id" class="sx-button" @click="$emit('inspect', row.candidate_id)">View diff ↗</button></td></tr></tbody></table></div></section>
    <FinalSelection :rows="agent.method.selection" title="Recorded integration candidates → final dev selection" @inspect="$emit('inspect', $event)" />
  </div>
</template>
