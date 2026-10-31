# Approved project page direction

- Date: 2026-10-30
- User's exact selection: “a吧”
- Selected: A — Benchmark Atlas.
- Reviewed alternatives: `direction-a.html`, `direction-b.html`, `direction-c.html`, with matching previews.
- Implementation: a bright research portal inspired by the supplied Agents’ Last Exam reference, with a results-first section, expandable method/benchmark/harness catalogs, and an explicit log-backed analysis entry point.
- Scope: static GitHub Pages project page at `docs/public/project.html`; existing VitePress documentation remains available at the root docs index.

## Form and implementation assumptions

- The page is a public research landing page, not a replacement for the operational documentation.
- Current README result excerpts are shown as percentages and deltas from the initial harness; no new benchmark claims are invented.
- Detailed task-level analysis is wired as a modal/data hook and will be populated after raw run logs are supplied.
- Real repository assets are copied into `docs/public/project-assets/` so the page can deploy as a self-contained static artifact.
