"""Offline ALFWorld contracts; synthetic environments are not benchmark smoke."""

import asyncio
import io
import json
import shlex
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from flashrsi import _launch
from flashrsi.benchmarks import ALFWorld
from flashrsi.benchmarks.alfworld import SPLITS, TASK_TYPES
from flashrsi.config import load_config
from flashrsi.core import Trajectory
from flashrsi.integrations import _alfworld_process as process
from flashrsi.integrations import alfworld as integration
from flashrsi.runner import _BENCHMARKS


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "json_2.1.1"
    for split in SPLITS:
        for i, task_type in enumerate(TASK_TYPES):
            directory = root / split / f"{task_type}-{i}" / "trial_1"
            directory.mkdir(parents=True)
            (directory / "traj_data.json").write_text(
                json.dumps(
                    {
                        "task_type": task_type,
                        "plan": "SECRET_EXPERT_PLAN",
                        "turk_annotations": {
                            "anns": [{"task_desc": "SECRET_REFERENCE"}]
                        },
                    }
                ),
                encoding="utf-8",
            )
            (directory / "game.tw-pddl").write_text(
                json.dumps(
                    {
                        "solvable": True,
                        "fixture_id": f"{split}-{i}",
                    }
                ),
                encoding="utf-8",
            )
    return root


def test_native_splits_lazy_load_and_hidden_annotations(dataset):
    benchmark = ALFWorld({"data_path": str(dataset.parent)})
    assert benchmark._splits is None
    splits = benchmark.load()
    assert {k: len(v) for k, v in splits.items()} == {"train": 6, "dev": 6, "test": 6}
    assert splits == ALFWorld({"data_path": str(dataset)}).load()
    assert {t.metadata["native_split"] for t in benchmark.test} == {"valid_unseen"}
    assert "SECRET" not in repr(splits)
    assert all(t.ground_truth is None for group in splits.values() for t in group)
    assert len({t.task_id for group in splits.values() for t in group}) == 18


def test_filter_and_explicit_experiment_partition(dataset):
    benchmark = ALFWorld(
        {
            "data_path": str(dataset),
            "task_types": [TASK_TYPES[0]],
            "split_counts": {"train": 1, "dev": 1, "test": 1},
        }
    )
    assert all(len(v) == 1 for v in benchmark.load().values())
    files = sorted((dataset / "train").rglob("game.tw-pddl"))
    files[0].unlink()
    files[1].write_text('{"solvable": false}', encoding="utf-8")
    files[2].write_text("{}", encoding="utf-8")
    assert len(ALFWorld({"data_path": str(dataset)}).load()["train"]) == 3


@pytest.mark.parametrize(
    "config",
    [
        {"max_steps": True},
        {"max_steps": 0},
        {"admissible_commands": "false"},
        {"task_types": []},
        {"task_types": ["visual"]},
        {"mode": "thor"},
        {"seed": -1},
        {"seed": 2**32},
    ],
)
def test_invalid_config(config):
    with pytest.raises(ValueError):
        ALFWorld(config)


def test_requires_local_data_and_known_layout(tmp_path):
    with pytest.raises(ValueError, match="local benchmark.data_path"):
        ALFWorld({}).load()
    with pytest.raises(ValueError, match="native train"):
        ALFWorld({"data_path": str(tmp_path)}).load()


class FakeEnvironment:
    def reset(self):
        self.actions = []
        return "Your task is to: put the apple on the table.", {
            "won": False,
            "admissible_commands": ["look"],
            "extra.expert_plan": ["SECRET"],
            "facts": "SECRET",
        }

    def step(self, action):
        self.actions.append(action)
        if action == "crash":
            raise RuntimeError("native failure")
        return (
            "Observation",
            99,
            action == "lose",
            {
                "won": action == "win",
                "admissible_commands": ["look"],
                "extra.expert_plan": ["SECRET"],
                "facts": "SECRET",
            },
        )


def play(actions, *, max_steps=2, admissible_commands=False):
    env, output = FakeEnvironment(), io.StringIO()
    requests = [{"operation": "step", "action": a} for a in actions]
    requests.append({"operation": "grade"})
    process._serve(
        env,
        {"max_steps": max_steps, "admissible_commands": admissible_commands},
        io.StringIO("\n".join(map(json.dumps, requests))),
        output,
    )
    return env, [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize(
    "actions, won, steps",
    [
        (["win", "look"], True, 1),
        (["lose"], False, 1),
        (["look", "look", "win"], False, 2),
        ([], False, 0),
    ],
)
def test_success_is_native_won_not_score_done_or_claim(actions, won, steps):
    env, rows = play(actions)
    assert rows[-1] == {"won": won, "steps": steps}
    assert len(env.actions) == steps
    assert "SECRET" not in repr(rows)
    assert "admissible_commands" not in rows[0]


def test_native_error_latches_and_command_visibility_is_explicit():
    env, rows = play(["crash", "win"])
    assert "error" in rows[-1] and env.actions == ["crash"]
    _, rows = play(["look"], admissible_commands=True)
    assert rows[0]["admissible_commands"] == ["look"]
    assert "SECRET" not in repr(rows)


def test_native_registration_uses_single_game_without_expert(monkeypatch):
    calls = {}
    env = SimpleNamespace(seed=lambda seed: calls.update(seed=seed))
    gym = SimpleNamespace(
        register_game=lambda *a, **kw: calls.update(args=a, options=kw) or "native-id",
        make=lambda identifier: env,
    )
    tw = SimpleNamespace(gym=gym, EnvInfos=lambda **kw: kw)
    modules = {
        "numpy": SimpleNamespace(random=SimpleNamespace(seed=lambda seed: None)),
        "textworld": tw,
        "textworld.gym": gym,
        "alfworld.agents.environment.alfred_tw_env": SimpleNamespace(
            AlfredDemangler=lambda **kw: ("demangler", kw)
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    assert (
        process._environment(
            {
                "gamefile": "/one/game.tw-pddl",
                "seed": 42,
                "max_steps": 50,
                "admissible_commands": False,
            }
        )
        is env
    )
    assert calls["args"] == (
        "/one/game.tw-pddl",
        {"won": True, "admissible_commands": False},
    )
    assert calls["options"]["wrappers"] == [("demangler", {"shuffle": False})]
    assert calls["options"]["max_episode_steps"] == 50
    assert calls["seed"] == 42


@pytest.fixture
def fake_process(tmp_path, monkeypatch):
    # Exercise the real subprocess protocol and HTTP bridge with a synthetic
    # engine. No installed ALFWorld, benchmark data, or model is used.
    script = tmp_path / "engine.py"
    script.write_text(
        "import importlib.util, sys, json\n"
        + f"spec=importlib.util.spec_from_file_location('engine', {process.__file__!r})\n"
        + "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
        + "class Env:\n"
        + " def reset(self): return 'Initial observation', {'won': False}\n"
        + " def step(self, action):\n"
        + "  if action == 'crash': raise RuntimeError('failure')\n"
        + "  return 'Next observation', 0, action == 'win', {'won': action == 'win'}\n"
        + "module._serve(Env(), json.loads(sys.stdin.readline()), sys.stdin, sys.stdout)\n",
        encoding="utf-8",
    )
    original = subprocess.Popen

    def spawn(args, **kwargs):
        args = [
            str(script) if str(a).endswith("_alfworld_process.py") else a for a in args
        ]
        return original(args, **kwargs)

    monkeypatch.setattr(integration.subprocess, "Popen", spawn)
    monkeypatch.setattr(integration, "_check_runtime", lambda: None)
    monkeypatch.setattr(integration, "token_urlsafe", lambda size: "-fixture-token")


@pytest.mark.parametrize("action, status", [("win", "finished"), ("crash", "error")])
def test_full_bridge_client_provenance_and_cleanup(
    dataset, fake_process, action, status
):
    benchmark = ALFWorld({"data_path": str(dataset)})
    benchmark.load()
    task = benchmark.test[0]
    target = SimpleNamespace(name="miniagent", config={})
    seen_paths = []

    async def run(prompt, working_dir):
        seen_paths.append(working_dir)
        assert "SECRET" not in prompt
        assert list(working_dir.iterdir()) == [working_dir / "alfworld.py"]
        line = prompt.split("submit one environment action:\n")[1].splitlines()[0]
        args = shlex.split(line)[:-1]
        token = next(
            a.removeprefix("--token=") for a in args if a.startswith("--token=")
        )
        url = args[args.index("--bridge") + 1]
        opener = build_opener(ProxyHandler({}))
        with pytest.raises(HTTPError) as exc:
            opener.open(
                Request(url, b"{}", {"Authorization": "Bearer wrong"}), timeout=5
            )
        assert exc.value.code == 403
        with opener.open(
            Request(
                url, b'{"operation":"grade"}', {"Authorization": "Bearer " + token}
            ),
            timeout=5,
        ) as response:
            assert "error" in json.load(response)
        response = subprocess.run(
            args + [action], capture_output=True, text=True, timeout=10
        )
        assert response.returncode == (0 if action == "win" else 1)
        return Trajectory(
            output=token,
            messages=({"type": "ALFWorldVerifier", "won": True},),
            usage={"input_tokens": 7},
        )

    target.run = run
    integration.bind(target, benchmark)
    for _ in range(2):
        result = asyncio.run(target._env_runner(target, task))
        assert result.status == status
        assert result.output == "[REDACTED]"
        assert result.usage["input_tokens"] == 7
        result = replace(result, task=task)
        assert benchmark.grade((result,))[0].metrics["success"] == (action == "win")
        if status == "finished":
            assert result.messages[-1]["steps"] == 1
            assert sum(m["type"] == "ALFWorldVerifier" for m in result.messages) == 1
            bad = {**result.messages[-1], "game_sha256": "changed"}
            with pytest.raises(ValueError, match="host verifier"):
                benchmark.grade((replace(result, messages=(bad,)),))
    assert seen_paths[0] != seen_paths[1]
    assert not any(path.exists() for path in seen_paths)


def test_mutated_game_rejected_before_agent(dataset, fake_process):
    benchmark = ALFWorld({"data_path": str(dataset)})
    benchmark.load()
    target = SimpleNamespace(name="miniagent", config={})
    integration.bind(target, benchmark)
    task = benchmark.test[0]
    benchmark._games[task.task_id][0].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after load"):
        asyncio.run(target._env_runner(target, task))
    with pytest.raises(ValueError, match="host verifier"):
        benchmark.grade((Trajectory(task=task, output="success"),))


def test_registry_launcher_and_example():
    assert _BENCHMARKS["alfworld"] is ALFWorld
    config = load_config(Path(__file__).parents[1] / "examples/alfworld_opro.yaml")
    plan = _launch._plan(config)
    assert "alfworld" in plan["extras"]
    assert not any("Docker" in item for item in plan["prerequisites"])


def test_runtime_and_shell_requirements(monkeypatch):
    monkeypatch.setattr(integration.os, "name", "nt")
    with pytest.raises(ValueError, match="Linux/WSL/macOS"):
        integration._check_runtime()
    monkeypatch.setattr(integration, "_check_runtime", lambda: None)
    with pytest.raises(ValueError, match="include Bash"):
        integration.bind(SimpleNamespace(name="claude_code", config={}), ALFWorld({}))
