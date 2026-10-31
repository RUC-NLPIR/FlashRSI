# Pi Python port baseline

This Python runtime ports the supported headless agent loop, built-in tools,
resource loading, and prompt text from [Pi](https://github.com/badlogic/pi-mono),
version **v1.4.0**, commit `4a080252f06caf63a525d7873c5d94d3c23887e0`.

The upstream source is distributed under the MIT license; its original notice
is preserved in [LICENSE](LICENSE). FlashRSI's adapter and framework remain
under the repository's Apache-2.0 license.

The Python port runs from the selected Agent Snapshot without Node.js, npm, or
the Pi CLI. Supported behavior and parity limits are documented in
`docs/agent-integration.md` in the FlashRSI repository. This is a partial semantic
port, and does not implement every upstream CLI, provider, or extension feature.
