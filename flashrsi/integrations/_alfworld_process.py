"""Own one native text environment; expose observations, never expert metadata."""

import contextlib
import json
import random
import sys


def _environment(setup):
    import numpy as np
    import textworld
    import textworld.gym
    from alfworld.agents.environment.alfred_tw_env import AlfredDemangler

    random.seed(setup["seed"])
    np.random.seed(setup["seed"] % (2**32))
    # Same native registration/demangling as AlfredTWEnv, restricted to the
    # selected game. No training expert, planner, or visual environment.
    env_id = textworld.gym.register_game(
        setup["gamefile"],
        textworld.EnvInfos(won=True, admissible_commands=setup["admissible_commands"]),
        max_episode_steps=setup["max_steps"],
        wrappers=[AlfredDemangler(shuffle=False)],
        asynchronous=False,
    )
    env = textworld.gym.make(env_id)
    env.seed(setup["seed"])
    return env


def _serve(env, setup, source, output):
    steps, done, error = 0, False, None
    obs, infos = env.reset()
    won = bool(infos["won"])

    def observation():
        result = {"observation": obs, "done": done, "steps": steps}
        if setup["admissible_commands"]:
            result["admissible_commands"] = list(infos["admissible_commands"])
        return result

    def send(result):
        print(
            json.dumps(result, ensure_ascii=True, allow_nan=False),
            file=output,
            flush=True,
        )

    send(observation())
    for line in source:
        request = json.loads(line)
        if request.get("operation") == "grade":
            send({"error": error} if error else {"won": won, "steps": steps})
            continue
        action = request.get("action")
        if (
            request.get("operation") != "step"
            or not isinstance(action, str)
            or not action.strip()
        ):
            send({"error": "Use a nonempty text action"})
        elif error:
            send({"error": error})
        elif done or won or steps >= setup["max_steps"]:
            send({"error": "Episode finished; no further actions allowed"})
        else:
            try:
                obs, _, native_done, infos = env.step(action)
                steps += 1
                won = bool(infos["won"])
                done = bool(native_done or won or steps >= setup["max_steps"])
                send(observation())
            except Exception as exc:
                error = f"Native ALFWorld step failed ({type(exc).__name__})"
                send({"error": error})


def main():
    setup = json.loads(sys.stdin.readline())
    output = sys.stdout
    # Native diagnostics must not corrupt the JSON protocol.
    with contextlib.redirect_stdout(sys.stderr):
        env = _environment(setup)
        try:
            _serve(env, setup, sys.stdin, output)
        finally:
            env.close()


if __name__ == "__main__":
    main()
