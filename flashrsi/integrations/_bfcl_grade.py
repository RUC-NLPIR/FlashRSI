"""Replay validated literal calls using both official BFCL conversation checks."""

import argparse
import contextlib
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

from ._bfcl_native import score_conversation


def evaluate(root):
    if version("mpmath") != "1.3.0":
        raise ValueError("BFCL native evaluation requires mpmath==1.3.0")
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "trace.json").read_text(encoding="utf-8"))
    if evidence.get("complete") is not True or evidence.get("interrupted") is not None:
        raise ValueError("BFCL conversation incomplete or interrupted")
    if type(evidence.get("protocol_valid")) is not bool:
        raise ValueError("Invalid BFCL protocol verdict")
    trace = evidence.get("trace")
    if not isinstance(trace, list) or len(trace) != len(request["row"]["question"]):
        raise ValueError("Invalid BFCL conversation trace")
    if any(
        not isinstance(turn, list)
        or any(
            not isinstance(batch, list)
            or not batch
            or any(not isinstance(call, str) for call in batch)
            for batch in turn
        )
        for turn in trace
    ):
        raise ValueError("Invalid BFCL literal-call trace")
    result = score_conversation(
        root / "native", request["row"], request["reference"], trace
    )
    fields = ("state_and_response_valid", "irrelevance_valid")
    if any(type(result.get(field)) is not bool for field in fields):
        raise ValueError("Invalid official BFCL evaluator result")
    return {
        **{field: result[field] for field in fields},
        "protocol_valid": evidence["protocol_valid"],
    }


def main(root):
    try:
        # Native assertion text can contain gold calls and expected state.
        with open(os.devnull, "w") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = evaluate(root)
    except Exception as exc:
        print(f"BFCL evaluator failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/world"))
    raise SystemExit(main(parser.parse_args().root))
