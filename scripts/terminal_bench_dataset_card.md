# Terminal-Bench 2.0 native tasks

This directory mirrors the native task files for `terminal-bench@2.0` from
[`laude-institute/terminal-bench-2`](https://github.com/laude-institute/terminal-bench-2)
at commit `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`. The source collection is
identified by Harbor's pinned
[`v0.23.0` registry](https://raw.githubusercontent.com/harbor-framework/harbor/v0.23.0/registry.json).

## Files

- `tasks.tar.gz` preserves each complete native task directory, including its
  instructions, task configuration, environment build files and resources,
  verifier tests, and reference solution. Task directories are at the archive
  root. File contents and executable permissions are retained; archive timestamps
  and owner identifiers are normalized for reproducible preparation.
- `tasks.parquet` is a browsing index with `id`, `question`, `task_path`,
  `task_checksum`, `category`, and `difficulty`. The final two columns may be null.
  `question` is Harbor's parsed instruction; it does not contain the reference
  solution. The index alone does not provide an executable task environment.
- `manifest.json` records the source revision, archive and index hashes, task
  count, and Harbor checksums for the archived task directories.

No official training splits are added. FlashRSI-Lite constructs reproducible
train/dev/test partitions when loading the collection, using its configured seed.
The task checksum includes all original task files. Harbor runs the native tests
against the environment after the agent finishes; the browsing index is not a
text-answer grading dataset. FlashRSI passes the instruction to the agent, while
Harbor handles the task environment and verifier.

## Runtime resources

The archive contains task definitions and their bundled resources, not Docker
image layers. The tasks reference prebuilt Docker images that still need to be
pulled separately. Building images from the included Dockerfiles and completing
some tasks also requires external package repositories, source repositories,
models, or datasets. Downloading this archive does not make execution offline.
Reference solutions are retained as upstream artifacts; they are not included in
the instructions passed to the agent.

## Preparation and provenance

From FlashRSI-Lite with Python 3.12 or newer:

```bash
uv run --extra all --extra harbor python scripts/prepare_terminal_bench.py
```

An existing checkout of the pinned source can be used with `--source-dir PATH`.
This performs offline preparation. The script writes only the `terminal_bench/`
subdirectory under its output directory; it does not upload data or rewrite other
benchmarks or the repository's root dataset card. Rebuilding with the same source
files, permissions, and dependency versions produces the same archive and index.

The pinned source tree does not contain a LICENSE file. The upstream repository
provides an
[`Apache-2.0` LICENSE](https://github.com/harbor-framework/terminal-bench-2/blob/2fd12b88aafdd04a52c298e3940bcb189f9766d6/LICENSE)
at the separately identified revision
`2fd12b88aafdd04a52c298e3940bcb189f9766d6`. That link records upstream licensing
information; this mirror does not assign a new license to the archived revision
or its bundled third-party assets.
