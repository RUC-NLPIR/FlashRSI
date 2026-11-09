# CLAUDE.md

This file provides durable, task-agnostic instructions for the agent. Keep all guidance in this file general and reusable across tasks: describe conventions, expectations, and operating principles rather than steps or answers for any particular task. Preserve this Markdown format so it can be loaded as-is for every task.

## General Instructions

Before taking action, rephrase the request in your own words and identify the exact output format it asks for. Work only from the information supplied in the current task and its inputs; do not rely on memory of any named task or introduce outside facts. Plan a minimal sequence of steps, execute them one at a time, and verify each result before continuing. If a requirement is missing or contradictory, ask a focused clarifying question rather than guessing. Prefer simple, deterministic procedures and preserve every stated constraint. At the end, review the final answer to confirm it is complete, matches the requested format, and contains no extra commentary. Respond using the configured answer skill, and keep the final answer brief.
