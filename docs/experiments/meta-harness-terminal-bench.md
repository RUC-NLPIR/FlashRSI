---
title: Meta-Harness × Terminal-Bench · Experiment notebook
description: Browse archived evolution decisions, selection evidence, and resource diffs for Meta-Harness on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/meta_harness.json" />
</ClientOnly>
