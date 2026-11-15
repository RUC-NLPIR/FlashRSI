---
title: EvoPrompt × Terminal-Bench · Population arena
description: Browse archived evolution decisions, selection evidence, and resource diffs for EvoPrompt on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/evoprompt.json" />
</ClientOnly>
