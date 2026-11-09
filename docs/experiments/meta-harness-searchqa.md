---
title: Meta-Harness × SearchQA · Experiment notebook
description: Inspect the recorded selection process, resource changes, and algorithm events for Meta-Harness on SearchQA.
layout: page
sidebar: false
outline: false
editLink: false
footer: false
---

<script setup>
import { defineAsyncComponent } from 'vue'
// Keep client-rendered static nodes out of VitePress's lean page bundle.
const SelectionExplorer = defineAsyncComponent(() => import('../.vitepress/theme/SelectionExplorer.vue'))
</script>

<ClientOnly>
  <SelectionExplorer data-path="/experiment-data/searchqa/meta_harness.json" />
</ClientOnly>
