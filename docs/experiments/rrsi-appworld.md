---
title: RRSI × AppWorld · Round tournament
description: Inspect archived evolution decisions, Snapshot changes, and file comparisons for RRSI on AppWorld.
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
  <SelectionExplorer data-path="/experiment-data/appworld/rrsi.json" />
</ClientOnly>
