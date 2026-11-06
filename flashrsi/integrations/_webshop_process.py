"""Run in the separate upstream Python environment; stdlib syntax supports 3.8."""

import contextlib
import hashlib
import json
import os
import random
import sys
from pathlib import Path


def _environment(setup):
    root = Path(setup["native_root"])
    sys.path.insert(0, str(root))
    random.seed(setup["seed"])
    import numpy as np

    np.random.seed(setup["seed"])
    from web_agent_site.engine import engine
    from web_agent_site.envs import WebAgentTextEnv

    # Upstream defaults to the 1k preview; select full resources without editing it.
    engine.DEFAULT_ATTR_PATH = str(root / "data/items_ins_v2.json")
    env = WebAgentTextEnv(
        observation_mode="text",
        file_path=str(root / "data/items_shuffle.json"),
        num_products=None,
        human_goals=True,
        show_attrs=False,
    )
    try:
        baseline = (root / "baseline_models/data/human_goals.json").read_bytes()
        if hashlib.sha256(baseline).hexdigest() != setup["goal_order_sha256"]:
            raise ValueError("WebShop baseline goal order changed")
        # Match the official baseline's process_goal normalization, retaining
        # position rather than index(text), which is ambiguous for duplicates.
        actual = [
            g["instruction_text"]
            .lower()
            .replace('"', "")
            .replace("'", "")
            .split(", and price lower than")[0]
            .strip()
            for g in env.server.goals
        ]
        if actual != json.loads(baseline):
            raise ValueError("WebShop runtime goals do not match the pinned task order")
    except BaseException:
        env.close()
        raise
    return env


def _serve(env, setup, source, output):
    obs, _ = env.reset(session=setup["goal_index"])
    goal = env.server.user_sessions[env.session]["goal"]
    goal_checksum = hashlib.sha256(
        json.dumps(goal, sort_keys=True).encode()
    ).hexdigest()
    steps, purchased, done, reward, error = 0, False, False, 0.0, None

    def send(value):
        print(
            json.dumps(value, ensure_ascii=True, allow_nan=False),
            file=output,
            flush=True,
        )

    def public():
        # Native done HTML contains reward/debug fields. Once purchased, no
        # more decisions are possible; retain those fields only for host grading.
        return {
            "observation": "Purchase completed." if purchased else obs,
            "available_actions": {} if done else env.get_available_actions(),
            "done": done,
            "steps": steps,
        }

    send({"public": public(), "goal_checksum": goal_checksum})
    for line in source:
        request = json.loads(line)
        if request.get("operation") == "grade":
            send(
                {"error": error}
                if error
                else {
                    "reward": reward,
                    "purchased": purchased,
                    "steps": steps,
                    "goal_checksum": goal_checksum,
                }
            )
            continue
        action = request.get("action")
        if (
            request.get("operation") != "step"
            or not isinstance(action, str)
            or not action.strip()
        ):
            send({"error": "Use one nonempty WebShop action"})
        elif error:
            send({"error": error})
        elif done:
            send({"error": "Episode finished; no further actions allowed"})
        else:
            try:
                obs, native_reward, purchased, _ = env.step(action)
                purchased = bool(purchased)
                reward = float(native_reward) if purchased else 0.0
                steps += 1
                done = purchased or steps >= setup["max_steps"]
                send(public())
            except Exception as exc:
                error = "Native WebShop step failed ({})".format(type(exc).__name__)
                send({"error": error})


def main():
    setup = json.loads(sys.stdin.readline())
    # Lucene/JVM diagnostics bypass Python's redirect_stdout. Keep a dedicated
    # protocol descriptor and send native stdout to stderr before importing it.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    with contextlib.redirect_stdout(sys.stderr):
        try:
            env = _environment(setup)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "error": "WebShop native initialization failed: {}: {}".format(
                            type(exc).__name__, exc
                        )
                    }
                ),
                file=output,
                flush=True,
            )
            return
        try:
            _serve(env, setup, sys.stdin, output)
        finally:
            env.close()


if __name__ == "__main__":
    main()
