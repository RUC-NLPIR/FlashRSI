"""Watch a real experiment PID and resume only recorded transient failures.

This external supervisor changes no experiment recipe or cached result. It can
attach to an existing process via its setup process record. Resume attempts use
the identical command and are bounded, recorded, and delayed after failures.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._parallel_plan_migration import atomic_json  # noqa: E402
from scripts.run_searchqa_experiment import _exclusive  # noqa: E402


def _read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def _alive(pid):
    state = subprocess.run(
        ["ps", "-p", str(pid), "-o", "state=,args="],
        text=True,
        capture_output=True,
        check=False,
    )
    return state.returncode == 0 and not state.stdout.lstrip().startswith(
        "Z"
    ), state.stdout


def _failure(experiment, status):
    message = status.get("error", "")
    key = None
    if "; trajectory: " in message:
        path = Path(message.rsplit("; trajectory: ", 1)[1]).resolve()
        if not path.is_relative_to((experiment / "cache/errors").resolve()):
            return False, message, key
        record = _read(path)
        message = record.get("trajectory", {}).get("error_message", message)
        key = record.get("key")
    transient = any(
        text in message.lower()
        for text in (
            "error code: 429",
            "error code: 500",
            "error code: 502",
            "error code: 503",
            "error code: 504",
            "timeout",
            "timed out",
            "connection error",
            "generation did not complete: length",
            "llm worker did not finish: length",
        )
    )
    return transient, message, key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness", choices=("miniagent", "claude_code"), required=True
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--process-record", type=Path, required=True)
    parser.add_argument("--max-resumes", type=int, default=32)
    args = parser.parse_args()
    experiment = args.run_root.resolve() / "full" / args.harness
    state_path = experiment / "supervisor.json"
    with _exclusive(experiment / "supervisor.lock"):
        state = _read(state_path)
        state.setdefault("resumes", [])
        state.update(supervisor_pid=os.getpid(), status="watching")
        record = _read(args.process_record)
        command = record["command"]
        entrypoints = {
            "scripts/run_searchqa_parallel_experiment.py",
            "scripts/run_searchqa_recoverable_experiment.py",
            "scripts/run_searchqa_protocol_experiment.py",
        }
        selected = [entry for entry in command if entry in entrypoints]
        if len(selected) != 1:
            raise ValueError("Process record must use a frozen experiment entrypoint")
        entrypoint_name = Path(selected[0]).name
        child = None
        while True:
            state["observed_at"] = datetime.now(timezone.utc).isoformat()
            pid = record["pid"]
            alive, description = _alive(pid)
            if child is not None:
                alive = child.poll() is None
            if alive:
                if entrypoint_name not in description or (
                    f"--harness {args.harness}" not in description
                ):
                    raise ValueError("Observed PID no longer matches this experiment")
                state.update(status="watching", experiment_pid=pid)
                atomic_json(state_path, state)
                time.sleep(15)
                continue
            result = _read(experiment / "result.json")
            if result.get("status") == "finished":
                state["status"] = "finished"
                atomic_json(state_path, state)
                return 0
            status = _read(experiment / "status.json")
            transient, reason, key = _failure(experiment, status)
            previous = sum(item.get("request_key") == key for item in state["resumes"])
            if (
                status.get("pid") != pid
                or not transient
                or len(state["resumes"]) >= args.max_resumes
                or (key is not None and previous >= 3)
            ):
                state.update(
                    status="needs_attention", reason=reason, experiment_pid=pid
                )
                atomic_json(state_path, state)
                print(
                    json.dumps(
                        {
                            "harness": args.harness,
                            "status": "needs_attention",
                            "reason": reason,
                        }
                    ),
                    flush=True,
                )
                return 1
            delay = min(30 * 2**previous, 300)
            state.update(status="backoff", delay_seconds=delay, reason=reason)
            atomic_json(state_path, state)
            for _ in range(delay // 15):
                time.sleep(15)
            with Path(record["log"]).open("ab") as output:
                child = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            wake = subprocess.Popen(
                ["/usr/bin/caffeinate", "-i", "-w", str(child.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            state["resumes"].append(
                {
                    "previous_pid": pid,
                    "pid": child.pid,
                    "reason": reason,
                    "request_key": key,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            record.update(
                pid=child.pid, caffeinate_pid=wake.pid, supervisor_pid=os.getpid()
            )
            atomic_json(args.process_record, record)
            atomic_json(state_path, state)
            print(
                json.dumps(
                    {
                        "harness": args.harness,
                        "resumed_pid": child.pid,
                        "reason": reason,
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    raise SystemExit(main())
