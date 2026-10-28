import asyncio
import json
from dataclasses import replace

import pytest

from flashrsi.algorithms import ModularRSI
from flashrsi.algorithms.modular_rsi import MODULES
from flashrsi.core import Agent, Benchmark, Snapshot, Task, Trajectory


class ExternalTasks(Benchmark):
    name = "external"
    description = "Independent evolution and downstream tasks."
    primary_metric = "accuracy"
    metadata = {"evolution_source": {"source": "independent-fixture"}}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": tuple(Task(f"e{i}", f"e{i}") for i in range(3)),
                "dev": (Task("dev-private", "dev-private"),),
                "test": (Task("test-private", "test-private"),),
            }
        return self._splits

    def grade(self, trajectories):
        return tuple(
            replace(t, metrics={"accuracy": float(t.output or 0)}) for t in trajectories
        )


class Harness(Agent):
    name = "offline_modular"
    description = "Versioned offline solver or checkout editor."

    def __init__(self, config):
        super().__init__(config)
        self.seen, self.calls, self.attempts = [], [], {}
        self.script = script

    async def _run(self, prompt, working_dir=None):
        if self.config.get("role") == "worker":
            self.seen.append((prompt, self.snapshot.id))
            return self.script(prompt, working_dir)
        self.calls.append((self.snapshot.id, prompt))
        text = self.files_dir.joinpath("code/main.py").read_text()
        if (
            "BROKEN_RUNTIME" in text
            or "INCOMPATIBLE" in text
            and text.count("return 1") == 5
        ):
            return Trajectory(status="error", error_message="execution protocol broken")
        namespace = {}
        exec(text, namespace)
        value = sum(namespace[f"f{i}"]() for i in range(5))
        attempt = self.attempts.get((self.snapshot.id, prompt), 0)
        self.attempts[self.snapshot.id, prompt] = attempt + 1
        # e0 supplies mixed evidence, e1 negative, e2 positive.
        output = 1 if prompt == "e2" or prompt == "e0" and attempt % 2 == 0 else 0
        return Trajectory(
            output=str(output), messages=({"type": "Trace", "value": value},)
        )


def setup(tmp_path, script, **options):
    source = tmp_path / "source"
    (source / "code").mkdir(parents=True)
    (source / "assets").mkdir()
    (source / "components.yaml").write_text(
        "code: ['code/**']\nasset: ['assets/**']", newline="\n"
    )
    (source / "code/main.py").write_text(
        "\n\n".join(f"def f{i}():\n    return 0" for i in range(5)) + "\n", newline="\n"
    )
    (source / "assets/binary").write_bytes(b"\x00\xff")
    (source / "assets/binary").chmod(0o755)
    target = Harness(
        {
            "source_dir": str(source),
            "llm": {"model_name": "offline", "api_key": "target-secret"},
        }
    )
    target.calls, target.attempts = [], {}
    worker = Harness(
        {
            "source_dir": str(source),
            "role": "worker",
            "type": "agent",
            "llm": {"model_name": "offline", "api_key": "worker-secret"},
        }
    )
    worker.script, worker.seen = script, []
    algo = ModularRSI(
        {
            "num_epochs": 1,
            "num_rollouts": 2,
            "batch_size": 3,
            "modules": {module: ["code/main.py"] for module in MODULES},
            **options,
        },
        target=target,
        worker=worker,
        benchmark=ExternalTasks(),
    )
    return algo


def module_name(prompt):
    return next(
        line.removeprefix("Module: ")
        for line in prompt.splitlines()
        if line.startswith("Module: ")
    )


def script(prompt, directory):
    if prompt.startswith("[ModularRSI: analyze]"):
        return Trajectory(
            output=json.dumps(
                [
                    {
                        "target": "code/main.py",
                        "task_ids": ["e0", "e1"],
                        "rationale": "Recurring defect",
                        "change": "Reusable improvement",
                    }
                ]
            )
        )
    if prompt.startswith("[ModularRSI: edit]"):
        i = MODULES.index(module_name(prompt))
        path = directory / "code/main.py"
        path.write_text(
            path.read_text().replace(
                f"def f{i}():\n    return 0", f"def f{i}():\n    return 1"
            ),
            newline="\n",
        )
        return Trajectory(output="Applied general improvement.")
    if prompt.startswith("[ModularRSI: merge]"):
        sources = json.loads(
            prompt.split("Module reference directories (do not edit): ")[1]
        )
        path = directory / "code/main.py"
        content = path.read_text()
        for i, module in enumerate(MODULES):
            branch = (directory / sources[module] / "code/main.py").read_text()
            prefix = f"def f{i}():"
            before = prefix + content.split(prefix)[1].split("\n\n")[0]
            after = prefix + branch.split(prefix)[1].split("\n\n")[0]
            content = content.replace(before, after)
        path.write_text(content, newline="\n")
        return Trajectory(output="Integrated every module's changes.")
    if prompt.startswith("[ModularRSI: review]"):
        return Trajectory(
            output='{"accept": true, "reason": "Reusable and compatible"}'
        )
    return Trajectory(output="No integration repair necessary.")


def test_independent_branches_merge_shared_file_and_keep_native_snapshot(
    tmp_path, monkeypatch
):
    algo = setup(tmp_path, script)
    seed, worker_seed = algo.target.snapshot, algo.worker.snapshot
    run = tmp_path / "run"
    algo._run_dir = run
    for name in ("snapshots", "trajectories", "working"):
        (run / name).mkdir(parents=True)
    updates = []
    update = algo.target.update
    monkeypatch.setattr(
        algo.target, "update", lambda s: (updates.append(s.id), update(s))[-1]
    )
    final = asyncio.run(algo.evolve())
    assert final.files["code/main.py"].content.count(b"return 1") == 5
    assert final.files["assets/binary"] == seed.files["assets/binary"]
    assert algo.worker.snapshot == worker_seed
    assert updates == [final.id]
    assert {prompt for _, prompt in algo.target.calls} == {"e0", "e1", "e2"}
    # Every independent module starts from seed; Worker keeps its own version.
    edits = [
        (p, sid) for p, sid in algo.worker.seen if p.startswith("[ModularRSI: edit]")
    ]
    assert len(edits) == 5 and all(sid == seed.id for _, sid in edits)
    for prompt, _ in algo.worker.seen:
        assert "dev-private" not in prompt and "test-private" not in prompt
    groups = [
        json.loads(p.read_text())
        for p in run.joinpath("trajectories").glob("*-contrast_groups.json")
    ]
    assert groups[0]["groups"] == {
        "e0": "contrastive",
        "e1": "negative",
        "e2": "positive",
    }
    assert not list(run.joinpath("working").iterdir())
    for path in run.joinpath("snapshots").glob("*.json"):
        assert set(Snapshot.load(path).files) == set(seed.files)
    text = "".join(p.read_text() for p in run.joinpath("trajectories").glob("*.json"))
    assert "target-secret" not in text and "worker-secret" not in text


def test_current_module_checkouts_evolve_without_switching_worker(tmp_path):
    edited = []

    def edit(prompt, directory):
        if (
            prompt.startswith("[ModularRSI: edit]")
            and module_name(prompt) == "agent_loop"
        ):
            path = directory / "code/main.py"
            edited.append(path.read_text())
            value = len(edited)
            path.write_text(
                path.read_text().replace(
                    f"def f0():\n    return {value - 1}",
                    f"def f0():\n    return {value}",
                ),
                newline="\n",
            )
            return Trajectory(output="Improved the current module checkout.")
        return script(prompt, directory)

    algo = setup(tmp_path, edit, num_epochs=2)
    seed = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    seen = [
        sid
        for p, sid in algo.worker.seen
        if p.startswith("[ModularRSI: analyze]") and module_name(p) == "agent_loop"
    ]
    assert seen == [seed.id, seed.id]
    assert "def f0():\n    return 0" in edited[0]
    assert "def f0():\n    return 1" in edited[1]
    assert b"def f0():\n    return 2" in final.files["code/main.py"].content


def test_worker_can_use_a_different_harness_without_target_updates(
    tmp_path, monkeypatch
):
    class Editor(Harness):
        name = "independent_editor"

    algo = setup(tmp_path, script)
    source = tmp_path / "editor"
    source.mkdir()
    (source / "components.yaml").write_text("editor: ['editor.py']", newline="\n")
    (source / "editor.py").write_text("# Independent editor resources\n", newline="\n")
    worker = Editor({"type": "agent", "role": "worker", "source_dir": str(source)})
    original = worker.snapshot
    assert original.agent_type != algo.target.snapshot.agent_type
    assert original.root_id != algo.target.snapshot.root_id
    monkeypatch.setattr(
        worker, "update", lambda snapshot: pytest.fail("Worker version changed")
    )
    algo = ModularRSI(
        dict(algo.config), target=algo.target, worker=worker, benchmark=algo.benchmark
    )
    final = asyncio.run(algo.evolve())
    assert final.files["code/main.py"].content.count(b"return 1") == 5
    assert worker.snapshot == original
    assert all(sid == original.id for _, sid in worker.seen)


@pytest.mark.parametrize("problem", ["scope", "review"])
def test_generated_merge_passes_file_and_review_gates(tmp_path, problem):
    def edit(prompt, directory):
        result = script(prompt, directory)
        if problem == "scope" and prompt.startswith("[ModularRSI: merge]"):
            (directory / "assets/binary").write_bytes(b"unrelated merge change")
        if (
            problem == "review"
            and prompt.startswith("[ModularRSI: review]")
            and module_name(prompt) == "integration"
        ):
            return Trajectory(
                output='{"accept": false, "reason": "Unrelated integration"}'
            )
        return result

    algo = setup(tmp_path, edit)
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()) == seed


@pytest.mark.parametrize(
    "problem", ["scope", "syntax", "credential", "review", "runtime"]
)
def test_gates_reject_candidates_without_changing_module_seed(tmp_path, problem):
    def edit(prompt, directory):
        if prompt.startswith("[ModularRSI: edit]"):
            result = script(prompt, directory)
            path = directory / "code/main.py"
            content = path.read_text()
            if problem == "scope":
                (directory / "assets/binary").write_bytes(b"changed outside module")
            elif problem == "syntax":
                content = content.replace("return 1", "return (")
            elif problem == "credential":
                content = content.replace("return 1", 'return "target-secret"')
            elif problem == "runtime":
                content = content.replace("return 1", "return 1 # BROKEN_RUNTIME")
            path.write_text(content, newline="\n")
            return result
        if problem == "review" and prompt.startswith("[ModularRSI: review]"):
            return Trajectory(
                output='{"accept": false, "reason": "Task-specific change"}'
            )
        return script(prompt, directory)

    algo = setup(tmp_path, edit)
    seed = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert final.id == seed.id


def test_failed_combination_is_not_promoted(tmp_path):
    def edit(prompt, directory):
        result = script(prompt, directory)
        if prompt.startswith("[ModularRSI: edit]"):
            path = directory / "code/main.py"
            path.write_text(
                path.read_text().replace("return 1", "return 1 # INCOMPATIBLE"),
                newline="\n",
            )
        return result

    algo = setup(tmp_path, edit)
    seed = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert final.id == seed.id


def test_integration_can_repair_a_broken_combination_with_independent_worker(tmp_path):
    def edit(prompt, directory):
        result = script(prompt, directory)
        if prompt.startswith("[ModularRSI: edit]"):
            path = directory / "code/main.py"
            path.write_text(
                path.read_text().replace("return 1", "return 1 # INCOMPATIBLE"),
                newline="\n",
            )
        if prompt.startswith("[ModularRSI: integrate]"):
            path = directory / "code/main.py"
            path.write_text(
                path.read_text().replace(" # INCOMPATIBLE", ""), newline="\n"
            )
        return result

    algo = setup(tmp_path, edit)
    seed = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert final.files["code/main.py"].content.count(b"return 1") == 5
    assert [
        (p, sid)
        for p, sid in algo.worker.seen
        if p.startswith("[ModularRSI: integrate]")
    ][0][1] == seed.id


def test_historical_success_pairs_with_current_negative_evidence(tmp_path):
    algo = setup(tmp_path, script)
    tasks, memory = (algo.benchmark.train[0],), {}
    first = asyncio.run(
        algo._contrast(algo.target.snapshot, tasks, memory, "agent_loop")
    )
    assert first[0]["group"] == "contrastive"

    async def fail(prompt, working_dir=None):
        return Trajectory(output="0")

    algo.target._run = fail
    second = asyncio.run(
        algo._contrast(algo.target.snapshot, tasks, memory, "agent_loop")
    )
    assert second[0]["group"] == "negative"
    assert second[0]["historical_success"]["trajectory"]["output"] == "1"


def test_findings_rank_distinct_task_support_not_duplicate_votes(tmp_path):
    algo = setup(tmp_path, script, edit_budget=2)
    algo.config.modules.agent_loop.append("assets/binary")
    values = [
        {
            "target": "code/main.py",
            "task_ids": ["e0", "e0"],
            "rationale": "A",
            "change": "B",
        },
        {
            "target": "code/main.py",
            "task_ids": ["e0"],
            "rationale": "C",
            "change": "D",
        },
        {
            "target": "assets/binary",
            "task_ids": ["e0", "e1"],
            "rationale": "E",
            "change": "F",
        },
    ]
    findings = algo._findings(json.dumps(values), "agent_loop", algo.benchmark.train)
    assert [row["target"] for row in findings] == [
        "assets/binary",
        "code/main.py",
    ]
    assert findings[1]["task_ids"] == ["e0"] and len(findings[1]["proposals"]) == 2
    values[0]["task_ids"] = ["test-private"]
    with pytest.raises(ValueError, match="supplied tasks"):
        algo._findings(json.dumps(values), "agent_loop", algo.benchmark.train)


def test_worker_failure_restores_version_and_cleans_checkouts(tmp_path):
    def fail(prompt, directory):
        if directory is not None:
            return Trajectory(status="error", error_message="worker failed")
        return script(prompt, directory)

    algo = setup(tmp_path, fail)
    worker_seed, seed = algo.worker.snapshot, algo.target.snapshot
    with pytest.raises(RuntimeError, match="worker failed"):
        asyncio.run(algo.evolve())
    assert algo.worker.snapshot == worker_seed and algo.target.snapshot == seed


@pytest.mark.parametrize(
    "field,value",
    [
        ("num_rollouts", 1),
        ("num_epochs", True),
        ("integration_epochs", 0),
        ("validation_samples", -1),
    ],
)
def test_parameter_validation(tmp_path, field, value):
    with pytest.raises(ValueError, match=field):
        setup(tmp_path, script, **{field: value})


def test_accepts_regular_train_and_requires_existing_module_files(tmp_path):
    algo = setup(tmp_path, script)
    algo.benchmark.metadata = {}
    algo._check()
    algo.config.modules.tool_use = ["missing.py"]
    with pytest.raises(ValueError, match="module file"):
        algo._check()
    algo.config.modules.tool_use = ["code/main.py"]
    algo._check()  # Shared files are integrated from independent native checkouts.
    algo.benchmark._splits["test"] = (Task("e0", "different prompt"),)
    with pytest.raises(ValueError, match="disjoint"):
        algo._check()


def test_same_dataset_tasks_can_share_policy_and_environment(tmp_path):
    algo = setup(tmp_path, script)
    algo.benchmark.metadata = {}
    algo.benchmark._splits = {
        role: tuple(
            replace(t, question="Shared domain policy", env="/domain") for t in tasks
        )
        for role, tasks in algo.benchmark._splits.items()
    }
    algo._check()


@pytest.mark.parametrize("damage", ["empty-train", "duplicate-train", "dev", "test"])
def test_regular_train_still_requires_unique_heldout_task_ids(tmp_path, damage):
    algo = setup(tmp_path, script)
    algo.benchmark.metadata = {}
    if damage == "empty-train":
        algo.benchmark._splits["train"] = ()
    elif damage == "duplicate-train":
        algo.benchmark._splits["train"] += (algo.benchmark.train[0],)
    else:
        algo.benchmark._splits[damage] = (
            replace(algo.benchmark.train[0], question="Different"),
        )
    with pytest.raises(ValueError, match="train|disjoint"):
        algo._check()


def test_runner_freezes_modules_before_one_downstream_test(tmp_path, monkeypatch):
    from flashrsi import runner
    from flashrsi.config import load_config

    monkeypatch.setattr(ExternalTasks, "metadata", {})
    algo = setup(tmp_path, script)
    monkeypatch.setitem(runner._AGENTS, Harness.name, Harness)
    monkeypatch.setitem(
        runner._BENCHMARKS, ExternalTasks.name, lambda config: ExternalTasks()
    )
    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "benchmark": {"name": ExternalTasks.name},
            "agent": {"name": Harness.name, **dict(algo.target.config)},
            "algorithm": {
                **dict(algo.config),
                "name": "modular_rsi",
                "worker": {"name": Harness.name, **dict(algo.worker.config)},
            },
        }
    )
    run_dir, result = asyncio.run(runner._run(config))
    assert result["status"] == "finished" and result["test_tasks"] == 1
    assert len(list((run_dir / "trajectories").glob("*-test.json"))) == 1
    assert not list((run_dir / "working").iterdir())
    assert load_config(run_dir / "config.yaml").algorithm.modules == algo.config.modules


def test_example_files_resolve_against_native_miniagent():
    from pathlib import Path

    import yaml

    from flashrsi.agents import MiniAgent

    config = yaml.safe_load(
        (Path(__file__).parent.parent / "examples/modular_rsi.yaml").read_text()
    )
    algo = ModularRSI(
        config["algorithm"],
        target=MiniAgent(config["agent"]),
        worker=MiniAgent(config["algorithm"]["worker"]),
        benchmark=ExternalTasks(),
    )
    assert len(algo.config.modules) == 5


def test_claude_extension_branches_edit_merge_and_freeze(tmp_path, monkeypatch):
    from pathlib import Path

    from flashrsi._launch import _load
    from flashrsi.agents import ClaudeCode

    config = _load(
        Path(__file__).parent.parent / "examples/modular_rsi_claude_code.yaml"
    )
    config.algorithm.batch_size = 3
    target = ClaudeCode(config.agent)
    modules = config.algorithm.modules
    seed = target.snapshot
    branch_inputs, evaluated = {}, []

    async def run(prompt, working_dir=None):
        evaluated.append(target.snapshot.id)
        return Trajectory(output="1")

    # Exercise real Claude resource snapshots without making SDK/model calls.
    monkeypatch.setattr(target, "_run", run)

    def edit(prompt, directory):
        if prompt.startswith("[ModularRSI: analyze]"):
            module = module_name(prompt)
            return Trajectory(
                output=json.dumps(
                    [
                        {
                            "target": modules[module][0],
                            "task_ids": ["e0"],
                            "rationale": "Reusable workflow improvement",
                            "change": "Clarify the extension's behavior",
                        }
                    ]
                )
            )
        if prompt.startswith("[ModularRSI: edit]"):
            module = module_name(prompt)
            branch_inputs[module] = {
                path: (directory / path).read_bytes()
                for paths in modules.values()
                for path in paths
            }
            path = directory / modules[module][0]
            if module == "hook":
                path.write_text(
                    json.dumps(
                        {
                            "hooks": {
                                "Stop": [
                                    {
                                        "hooks": [
                                            {
                                                "type": "prompt",
                                                "prompt": "Check task completion.",
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    )
                )
            else:
                path.write_text(path.read_text() + "\nCheck completion evidence.\n")
            return Trajectory(output="Updated one extension.")
        if prompt.startswith("[ModularRSI: merge]"):
            sources = json.loads(
                prompt.split("Module reference directories (do not edit): ")[1]
            )
            assert set(sources) == set(modules)
            for module, paths in modules.items():
                for path in paths:
                    (directory / path).write_bytes(
                        (directory / sources[module] / path).read_bytes()
                    )
            return Trajectory(output="Integrated the three extension branches.")
        if prompt.startswith("[ModularRSI: review]"):
            return Trajectory(output='{"accept": true, "reason": "Reusable"}')
        return Trajectory(output="No further changes.")

    worker = setup(tmp_path, edit).worker
    worker_seed = worker.snapshot
    algo = ModularRSI(
        config.algorithm, target=target, worker=worker, benchmark=ExternalTasks()
    )
    final = asyncio.run(algo.evolve())
    paths = {path for files in modules.values() for path in files}
    assert set(branch_inputs) == {"prompt", "skill", "hook"}
    for files in branch_inputs.values():
        assert files == {path: seed.files[path].content for path in paths}
    assert set(seed.changed_paths(final)) == paths
    assert final.id in evaluated and target.snapshot == final
    assert worker.snapshot == worker_seed
    for prompt, _ in worker.seen:
        assert "dev-private" not in prompt and "test-private" not in prompt


@pytest.mark.parametrize(
    "modules",
    [{}, {"prompt": ["code/main.py"]}, {"integration": ["code/main.py"]}],
)
def test_requires_complete_runtime_or_extension_module_set(tmp_path, modules):
    with pytest.raises(ValueError, match="five runtime modules.*three extension"):
        setup(tmp_path, script, modules=modules)


def test_extension_edit_cannot_change_other_module(tmp_path):
    algo = setup(
        tmp_path,
        script,
        modules={
            "prompt": ["code/main.py"],
            "skill": ["assets/binary"],
            "hook": ["assets/binary"],
        },
    )

    def illegal_edit(prompt, directory):
        (directory / "assets/binary").write_bytes(b"changed")
        return Trajectory(output="Changed another module.")

    algo.worker.script = illegal_edit
    assert asyncio.run(algo._edit(algo.target.snapshot, "prompt", "edit")) is None


def test_malformed_candidate_output_fails_execution_gate(tmp_path, monkeypatch):
    algo = setup(tmp_path, script)

    async def malformed(*args, **kwargs):
        raise KeyError("missing stop_reason")

    monkeypatch.setattr(algo.target, "rollout", malformed)
    assert not asyncio.run(
        algo._execution_gate(algo.target.snapshot, algo.benchmark.train, "agent_loop")
    )


@pytest.mark.parametrize("error", [ValueError, TypeError, KeyError, AttributeError])
@pytest.mark.parametrize("repair", [True, False])
def test_integration_protocol_errors_reach_independent_worker(
    tmp_path, monkeypatch, error, repair
):
    def edit(prompt, directory):
        result = script(prompt, directory)
        if prompt.startswith("[ModularRSI: edit]"):
            path = directory / "code/main.py"
            path.write_text(
                path.read_text().replace("return 1", "return 1 # MALFORMED"),
                newline="\n",
            )
        if repair and prompt.startswith("[ModularRSI: integrate]"):
            path = directory / "code/main.py"
            path.write_text(path.read_text().replace(" # MALFORMED", ""), newline="\n")
        return result

    algo = setup(tmp_path, edit)
    seed, worker_seed = algo.target.snapshot, algo.worker.snapshot
    rollout = algo.target.rollout

    async def malformed(tasks, *, snapshot=None):
        content = snapshot.files["code/main.py"].content
        if content.count(b"return 1") == 5 and b"MALFORMED" in content:
            raise error("missing stop_reason")
        return await rollout(tasks, snapshot=snapshot)

    monkeypatch.setattr(algo.target, "rollout", malformed)
    final = asyncio.run(algo.evolve())
    integrations = [
        (p, sid)
        for p, sid in algo.worker.seen
        if p.startswith("[ModularRSI: integrate]")
    ]
    assert len(integrations) == 1 and integrations[0][1] == seed.id
    assert "missing stop_reason" in integrations[0][0]
    assert "batch evaluation; failing task unknown" in integrations[0][0]
    assert algo.worker.snapshot == worker_seed
    if repair:
        assert final.files["code/main.py"].content.count(b"return 1") == 5
        assert b"MALFORMED" not in final.files["code/main.py"].content
    else:
        assert final.id == seed.id


@pytest.mark.parametrize("protocol_error", [True, False])
def test_partial_integration_does_not_disable_next_worker_repair(
    tmp_path, monkeypatch, protocol_error
):
    repairs = []

    def edit(prompt, directory):
        result = script(prompt, directory)
        if prompt.startswith("[ModularRSI: edit]"):
            path = directory / "code/main.py"
            path.write_text(
                path.read_text().replace("return 1", "return 1 # TOOL_BROKEN"),
                newline="\n",
            )
        if prompt.startswith("[ModularRSI: integrate]"):
            repairs.append(algo.worker.snapshot.id)
            path = directory / "code/main.py"
            if len(repairs) == 1:
                content = path.read_text().replace(
                    "# TOOL_BROKEN", "# TOOL_BROKEN; partial repair", 1
                )
            else:
                content = (
                    path.read_text()
                    .replace("; partial repair", "")
                    .replace(" # TOOL_BROKEN", "")
                )
            path.write_text(content, newline="\n")
        return result

    algo = setup(tmp_path, edit, integration_epochs=2)
    seed, worker_seed = algo.target.snapshot, algo.worker.snapshot
    rollout = algo.target.rollout
    worker_run = algo.worker._run

    async def broken_task(tasks, *, snapshot=None):
        tasks = tuple(tasks)
        source = snapshot.files["code/main.py"].content
        broken = source.count(b"return 1") == 5 and b"TOOL_BROKEN" in source
        if broken and protocol_error and any(t.task_id == "e2" for t in tasks):
            raise KeyError("read_file unavailable")
        rows = await rollout(tasks, snapshot=snapshot)
        return tuple(
            replace(t, status="error", error_message="read_file unavailable")
            if broken and t.task.task_id == "e2"
            else t
            for t in rows
        )

    async def broken_editor(prompt, working_dir=None):
        source = algo.worker.snapshot.files["code/main.py"].content
        if source.count(b"return 1") == 5 and b"TOOL_BROKEN" in source:
            return Trajectory(status="error", error_message="read_file unavailable")
        return await worker_run(prompt, working_dir)

    monkeypatch.setattr(algo.target, "rollout", broken_task)
    monkeypatch.setattr(algo.worker, "_run", broken_editor)
    final = asyncio.run(algo.evolve())
    # The first repair passes the e0/e1 sample but still cannot use file tools.
    assert repairs == [seed.id, seed.id]
    assert final.files["code/main.py"].content.count(b"return 1") == 5
    assert b"TOOL_BROKEN" not in final.files["code/main.py"].content
    assert algo.worker.snapshot == worker_seed


def test_module_runtime_error_does_not_disable_independent_worker(
    tmp_path, monkeypatch
):
    def edit(prompt, directory):
        if (
            prompt.startswith("[ModularRSI: edit]")
            and module_name(prompt) == "agent_loop"
        ):
            path = directory / "code/main.py"
            content = path.read_text()
            for value in (0, 1, 2):
                old = f"def f0():\n    return {value}"
                if old in content:
                    path.write_text(
                        content.replace(old, f"def f0():\n    return {value + 1}"),
                        newline="\n",
                    )
                    return Trajectory(output="Updated the loop.")
        return script(prompt, directory)

    algo = setup(tmp_path, edit, num_epochs=3)
    run, worker_run = algo.target._run, algo.worker._run

    async def broken_task(prompt, working_dir=None):
        source = algo.target.files_dir.joinpath("code/main.py").read_text()
        if prompt == "e2" and "def f0():\n    return 2" in source:
            return Trajectory(status="error", error_message="file tools unavailable")
        return await run(prompt, working_dir)

    async def broken_editor(prompt, working_dir=None):
        source = algo.worker.snapshot.files["code/main.py"].content
        if b"def f0():\n    return 2" in source:
            return Trajectory(status="error", error_message="file tools unavailable")
        return await worker_run(prompt, working_dir)

    monkeypatch.setattr(algo.target, "_run", broken_task)
    monkeypatch.setattr(algo.worker, "_run", broken_editor)
    final = asyncio.run(algo.evolve())
    editors = [
        sid
        for prompt, sid in algo.worker.seen
        if prompt.startswith("[ModularRSI: analyze]")
        and module_name(prompt) == "agent_loop"
    ]
    assert editors == [algo.worker.snapshot.id] * 3
    assert b"def f0():\n    return 3" in final.files["code/main.py"].content


def test_failed_integration_keeps_fully_validated_merge(tmp_path, monkeypatch):
    def edit(prompt, directory):
        result = script(prompt, directory)
        if prompt.startswith("[ModularRSI: integrate]"):
            path = directory / "code/main.py"
            path.write_text(
                path.read_text().replace("return 1", "return 1 # PARTIAL_BREAK", 1),
                newline="\n",
            )
        return result

    algo = setup(tmp_path, edit)
    run = algo.target._run

    async def broken(prompt, working_dir=None):
        result = await run(prompt, working_dir)
        if (
            prompt == "e2"
            and b"PARTIAL_BREAK"
            in algo.target.files_dir.joinpath("code/main.py").read_bytes()
        ):
            return replace(result, status="error", error_message="e2 runtime failure")
        return result

    monkeypatch.setattr(algo.target, "_run", broken)
    gates = []
    gate = algo._execution_gate

    async def observe(candidate, tasks, module):
        tasks = tuple(tasks)
        passed = await gate(candidate, tasks, module)
        gates.append((module, tuple(t.task_id for t in tasks), passed))
        return passed

    monkeypatch.setattr(algo, "_execution_gate", observe)
    final = asyncio.run(algo.evolve())
    # The integration edit passes its sample, then fails on the unsampled e2.
    assert gates[-3:] == [
        ("integration", ("e0", "e1", "e2"), True),
        ("integration", ("e0", "e1"), True),
        ("final", ("e0", "e1", "e2"), False),
    ]
    assert final.files["code/main.py"].content.count(b"return 1") == 5
    assert b"PARTIAL_BREAK" not in final.files["code/main.py"].content


@pytest.mark.parametrize("task_count", [1, 3])
def test_long_contrast_evidence_preserves_tasks_and_both_polarities(
    tmp_path, monkeypatch, task_count
):
    algo = setup(tmp_path, script, max_evidence_chars=4000)
    run = algo.target._run

    async def long_trace(prompt, working_dir=None):
        result = await run(prompt, working_dir)
        return replace(
            result,
            messages=({"type": "Trace", "text": "START" + '\\"\n汉' * 20000 + "END"},),
        )

    monkeypatch.setattr(algo.target, "_run", long_trace)
    memory = {}
    rows = asyncio.run(
        algo._contrast(
            algo.target.snapshot,
            algo.benchmark.train[:task_count],
            memory,
            "agent_loop",
        )
    )
    evidence = algo._contrast_evidence(rows)
    compact = json.loads(evidence)
    assert len(evidence) <= 4000
    assert [r["task_id"] for r in compact] == [r["task_id"] for r in rows]
    assert [r["group"] for r in compact] == [r["group"] for r in rows]
    mixed = compact[0]
    assert mixed["question"] == "e0" and mixed["group"] == "contrastive"
    assert mixed["success_count"] == mixed["failure_count"] == 1
    assert mixed["successes"][0]["metrics"]["accuracy"] == 1
    assert mixed["failures"][0]["metrics"]["accuracy"] == 0
    for row in compact:
        for record in row["successes"] + row["failures"]:
            assert "START" in record["trace"] and "END" in record["trace"]
            assert "…" in record["trace"]
    assert len(memory["e0"]["trajectory"]["messages"][0]["text"]) > 60000
    assert len(rows[0]["failures"][0]["messages"][0]["text"]) > 60000

    async def fail(prompt, working_dir=None):
        result = await long_trace(prompt, working_dir)
        return replace(result, output="0")

    monkeypatch.setattr(algo.target, "_run", fail)
    negative = asyncio.run(
        algo._contrast(
            algo.target.snapshot, algo.benchmark.train[:1], memory, "agent_loop"
        )
    )
    historical = json.loads(algo._contrast_evidence(negative))[0]
    assert historical["group"] == "negative" and not historical["successes"]
    assert historical["historical_success"]["snapshot_id"] == algo.target.snapshot.id
    assert historical["historical_success"]["trajectory"]["output"] == "1"
    assert historical["failures"][0]["output"] == "0"


def test_contrast_budget_too_small_fails_explicitly(tmp_path):
    algo = setup(tmp_path, script, max_evidence_chars=50)
    rows = asyncio.run(
        algo._contrast(algo.target.snapshot, algo.benchmark.train[:1], {}, "agent_loop")
    )
    with pytest.raises(ValueError, match="too small for contrast task IDs"):
        algo._contrast_evidence(rows)


def test_short_contrast_evidence_is_unchanged(tmp_path):
    algo = setup(tmp_path, script)
    rows = asyncio.run(
        algo._contrast(algo.target.snapshot, algo.benchmark.train, {}, "agent_loop")
    )
    assert algo._contrast_evidence(rows) == algo._evidence(rows)
