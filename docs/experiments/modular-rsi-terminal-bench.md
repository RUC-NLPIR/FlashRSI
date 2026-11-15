---
title: ModularRSI × Terminal-Bench · Branches and integration
description: Browse archived evolution decisions, selection evidence, and resource diffs for ModularRSI on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/modular_rsi.json" />
</ClientOnly>
