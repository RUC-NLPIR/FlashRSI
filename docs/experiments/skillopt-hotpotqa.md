---
title: SkillOpt × HotpotQA · Experiment explorer
description: Browse historical SkillOpt candidates, skill changes, development scores, and run logs.
layout: page
sidebar: false
outline: false
editLink: false
footer: false
---

<script setup>
import { defineAsyncComponent } from 'vue'
// Keep client-rendered static nodes out of VitePress's lean page bundle.
const ExperimentExplorer = defineAsyncComponent(() => import('../.vitepress/theme/ExperimentExplorer.vue'))
</script>

<ClientOnly>
  <ExperimentExplorer data-path="/experiment-data/skillopt-hotpotqa.json" />
</ClientOnly>
