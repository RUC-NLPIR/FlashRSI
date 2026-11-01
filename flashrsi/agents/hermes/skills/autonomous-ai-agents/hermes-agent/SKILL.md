---
name: hermes-agent
description: "Use the FlashRSI Hermes Snapshot's headless Python runtime, tools, sessions, and compression paths."
version: 1.0.0
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, flashrsi, snapshot, tools, sessions, compression]
    homepage: https://github.com/NousResearch/hermes-agent
---

# Hermes Agent Snapshot

This Snapshot is the FlashRSI headless Python realization of NousResearch Hermes
Agent v0.22.5. It runs the selected Snapshot files directly and keeps the model,
API key, endpoint, task directory, and session file in the role or task
configuration.

## Supported paths

- Chat Completions, OpenAI Responses, and Anthropic Messages over explicit HTTP.
- `terminal`, file, patch, search, todo, skill, and session-search tools.
- Multi-turn tool execution, retries, recovery, iteration budgets, output
  continuation, persistent JSON sessions, and context compression.
- Snapshot-local `SOUL.md`, `config.yaml`, project context files, and `skills/`.

Use `skills_list` to find available skills and `skill_view` to load one. Skill
files are read-only resources; prepare any external commands or credentials in
the task environment before using a skill.

## Snapshot boundary

This target does not start the Hermes CLI, Node.js, npm, or a host Hermes
profile. The full product's TUI, gateway, desktop, plugins/MCP, cron, delegated
agents, provider login/OAuth, and persistent memory service are outside this
headless target. Do not infer support for those surfaces from the upstream
product documentation; use the Snapshot runtime and role configuration as the
source of truth.
