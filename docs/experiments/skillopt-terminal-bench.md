---
title: SkillOpt × Terminal-Bench · Fast / slow skill updates
description: Browse archived evolution decisions, selection evidence, and resource diffs for SkillOpt on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/skillopt.json" />
</ClientOnly>
