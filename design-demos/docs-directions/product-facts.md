# Documentation sources

Verified on 2026-10-30:

- The supplied DeepSeek Harness reference is a documentation page with top search, grouped side navigation, page outline, GitHub edit links, and next-page navigation. https://deepseek-harness.github.io/deepseek-harness/en/guide/quickstart
- VitePress provides static Markdown pages and supports GitHub Pages with a repository base path and an Actions deployment. The stable 1.6.4 release is used, rather than the 2.0 alpha. https://vitepress.dev/guide/deploy
- Local source of truth: `pyproject.toml`, `flashrsi/cli.py`, `flashrsi/core/`, `flashrsi/agents/`, `flashrsi/algorithms/`, `flashrsi/benchmarks/`, and `examples/quickstart.yaml`.
- The local CLI exposes `run` and `evaluate`; the PDF's `eval` wording is documented as `evaluate`.
- Twelve algorithms and thirty benchmark suites are registered; MiniAgent, Claude Code, and Codex are implemented. Pi, Hermes, and OpenCode remain planned integrations.
- The quickstart has twelve local questions and a 6/3/3 train/dev/test split. It needs model credentials to perform evolution; it does not need Docker.
