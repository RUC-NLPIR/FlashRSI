---
title: SkillOpt × AppWorld · Fast / slow skill updates
description: Inspect archived evolution decisions, Snapshot changes, and file comparisons for SkillOpt on AppWorld.
layout: page
sidebar: false
outline: false
editLink: false
footer: false
---

<script setup>
import { defineAsyncComponent } from 'vue'
const SelectionExplorer = defineAsyncComponent(() => import('../.vitepress/theme/SelectionExplorer.vue'))
</script>

<ClientOnly>
  <SelectionExplorer data-path="/experiment-data/appworld/skillopt.json" />
</ClientOnly>
