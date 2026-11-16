---
title: OPRO × AppWorld · Optimization history
description: Inspect archived evolution decisions, Snapshot changes, and file comparisons for OPRO on AppWorld.
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
  <SelectionExplorer data-path="/experiment-data/appworld/opro.json" />
</ClientOnly>
