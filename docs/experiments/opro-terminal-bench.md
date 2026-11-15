---
title: OPRO × Terminal-Bench · Optimization history
description: Browse archived evolution decisions, selection evidence, and resource diffs for OPRO on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/opro.json" />
</ClientOnly>
