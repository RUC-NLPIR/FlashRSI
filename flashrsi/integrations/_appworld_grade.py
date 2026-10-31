"""Trusted native evaluator entry point; never accepts Agent code or verdicts."""

import contextlib
import json
import os
import sys
from importlib.metadata import version


def evaluate(task_id):
    os.environ["APPWORLD_ROOT"] = "/world"
    runtime_version = version("appworld")
    if runtime_version != "0.1.3.post1":
        raise ValueError("AppWorld runtime must be 0.1.3.post1")
    from appworld.evaluator import evaluate_task

    result = evaluate_task(
        task_id=task_id,
        experiment_name="current",
        suppress_errors=True,
        save_report=False,
    )
    if type(result.success) is not bool:
        raise ValueError("Official AppWorld evaluator success must be boolean")
    return {"success": result.success, "appworld_version": runtime_version}


def main(task_id):
    try:
        # Evaluator traces can contain private labels or expected answers.
        # Neither native prints nor traceback source lines enter trajectories.
        with open(os.devnull, "w") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                verdict = evaluate(task_id)
    except Exception as exc:
        print(
            f"AppWorld evaluator failed ({type(exc).__name__}); check image and data compatibility",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
