# JiuwenSwarm

JiuwenSwarm runs a single Target agent through its native Process SDK. FlashRSI starts a fresh process for each task, loads the selected Snapshot, and records the native output, events and usage. Choose `agent.work.normal` (default) or `agent.code.normal`. Configure a separate Worker under `algorithm.worker`.

| Component | Snapshot files |
| --- | --- |
| `code` | JiuwenSwarm’s `prompt_builder.py` and openJiuwen’s `react_agent.py` under `runtime/` |
| `skill` | `skills/**` |
| `tool` | `tools/<name>/tool.json` and `run.py`, plus any accompanying files |
| `config` | `config.yaml` |

Each task loads these two modules from its selected Snapshot. The pinned wheels supply their supporting packages and native Process CLI (JiuwenSwarm 0.2.8 and openJiuwen Agent Core 0.1.20). The adapter supplies the model connection at run time. [Pinned source revisions](../../flashrsi/agents/jiuwenswarm/upstream.json)

The native Process SDK exposes each Snapshot tool to the model and routes calls to its script in the current task workspace. A Worker with write access to the `tool` component can add one by creating its two files in the candidate checkout. Saving or restoring the Snapshot preserves the tool set. [Tool authoring example](../../flashrsi/agents/jiuwenswarm/tools/README.md)

## Configure a Docker-backed Target

From the repository root, install FlashRSI with the [installation guide](../guide/installation.md). Build the seven native wheels once for a Linux x86-64 Docker environment with BuildKit. The build needs access to the pinned GitHub and GitCode sources.

```bash
docker buildx build --platform linux/amd64 --output type=local,dest=.cache/jiuwenswarm/wheels - < flashrsi/agents/jiuwenswarm/wheels.Dockerfile
```

To start SkillOpt with an editable QA skill, create the initial source directory. The command expects a new output path.

```bash
uv run python -m scripts.prepare_jiuwenswarm_example --output .cache/jiuwenswarm/seed
```

Copy [the existing SearchQA quickstart](../../examples/quickstart_launch.yaml) next to the original so its data path still resolves. Replace the `agent` section with the following, using absolute paths to the directories you prepared.

```yaml
agent:
  name: jiuwenswarm
  mode: agent.work.normal
  source_dir: /absolute/path/to/.cache/jiuwenswarm/seed
  container_wheels: /absolute/path/to/.cache/jiuwenswarm/wheels
  skills: [qa]
  llm:
    model_name: YOUR_MODEL
    base_url: https://your-provider.example/v1
    api_key: null
```

Set the Target key with `FLASHRSI_AGENT_API_KEY`. Configure the Worker's model, base URL and key independently in the quickstart or with `FLASHRSI_WORKER_MODEL`, `FLASHRSI_WORKER_BASE_URL` and `FLASHRSI_WORKER_API_KEY`. Run the launcher with the path to your copy.

```bash
python scripts/run_experiment.py --config examples/jiuwenswarm.local.yaml
```

The launcher prepares the benchmark. Each SearchQA Target container installs the native wheels and their dependencies, then runs the selected skills and code with access to the configured model endpoint. For a host-executed Target, `agent.python` selects the Python interpreter with those dependencies installed.
