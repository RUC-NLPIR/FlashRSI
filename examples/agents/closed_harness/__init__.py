"""Closed harness adapter: explicitly pass versioned files to an injected SDK."""

from flashrsi.core import Agent


class SDKAgent(Agent):
    name = "example_sdk"
    description = "Pass the selected native configuration to an injected SDK."

    def __init__(self, config, *, sdk):
        super().__init__(config)
        self.sdk = sdk

    async def _run(self, prompt, working_dir=None):
        # Translate these into the chosen SDK version's supported settings or
        # plugin options. cwd must not silently replace this worker's config.
        return await self.sdk.execute(
            prompt=prompt,
            instructions=(self.files_dir / "CLAUDE.md").read_text(),
            skills_dir=self.files_dir / ".claude/skills",
            cwd=working_dir,
            model=self.config["llm"].get("model_name"),
        )
