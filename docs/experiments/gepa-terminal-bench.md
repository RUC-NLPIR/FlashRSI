---
title: GEPA × Terminal-Bench · Coverage frontier
description: Browse archived evolution decisions, selection evidence, and resource diffs for GEPA on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/gepa.json" />
</ClientOnly>
