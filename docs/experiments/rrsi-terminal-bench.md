---
title: RRSI × Terminal-Bench · Round tournament
description: Browse archived evolution decisions, selection evidence, and resource diffs for RRSI on Terminal-Bench.
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
  <SelectionExplorer data-path="/experiment-data/terminalbench/rrsi.json" />
</ClientOnly>
