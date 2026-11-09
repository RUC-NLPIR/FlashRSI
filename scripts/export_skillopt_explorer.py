"""Export the curated historical SkillOpt/SearchQA records for the docs explorer."""

import argparse
import difflib
import json
import re
from pathlib import Path


def export(source: Path) -> dict:
    agents = {}
    for name in ("miniagent", "claude_code"):
        directory = source / name
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        evaluations = [
            json.loads(line)
            for line in (directory / "evaluations.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        states = {}
        for state in json.loads(
            (directory / "skills/index.json").read_text(encoding="utf-8")
        ):
            states[state["snapshot_id"]] = {
                "/".join(Path(file["file"]).parts[2:]): (
                    directory / file["file"]
                ).read_text(encoding="utf-8")
                for file in state["files"]
            }

        decisions = []
        best = next(row["hard"] for row in evaluations if row["stage"] == "baseline")
        for line in (
            (directory / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            before = states.get(row["parent_id"], {})
            after = states.get(row.get("candidate_id"), {})
            files = []
            if row.get("candidate_id"):
                assert row["parent_id"] in states and row["candidate_id"] in states
                for path in sorted(before.keys() | after.keys()):
                    old, new = before.get(path, ""), after.get(path, "")
                    files.append(
                        {
                            "path": path,
                            "before": old,
                            "after": new,
                            "diff": list(
                                difflib.unified_diff(
                                    old.splitlines(),
                                    new.splitlines(),
                                    fromfile="before/" + path,
                                    tofile="after/" + path,
                                    lineterm="",
                                )
                            ),
                        }
                    )
            if row["accepted"]:
                best = row["score"]
            patch = row.get("patch") or {}
            decisions.append(
                {
                    "number": len(decisions) + 1,
                    "epoch": row["epoch"],
                    "kind": row["kind"],
                    "accepted": row["accepted"],
                    "score": row.get("score"),
                    "parentScore": row.get("baseline_score"),
                    "bestScore": best,
                    "reason": row.get("reason"),
                    "error": row.get("error"),
                    "explanation": patch.get("reasoning"),
                    "edits": [
                        {
                            k: edit[k]
                            for k in ("op", "path", "target", "content")
                            if k in edit
                        }
                        for edit in patch.get("edits", [])
                    ],
                    "files": files,
                }
            )

        assert (
            sum(row["accepted"] for row in decisions) == result["accepted_candidates"]
        )
        assert len(decisions) == result["candidate_decisions"]

        logs = []
        for path in sorted((source / "logs").glob("*.log")):
            if name in path.name or path.name == "full-v2.log":
                lines = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        record = None
                    # This pilot intentionally excludes sealed-test results, including
                    # the result summaries printed at the end of protocol logs.
                    if (
                        isinstance(record, dict)
                        and {"baseline", "evolved"} <= record.keys()
                    ):
                        line = "[Test result summary omitted from this explorer]"
                    elif isinstance(record, dict) and "insufficient_user_quota" in str(
                        record.get("reason", "")
                    ):
                        record["reason"] = (
                            "Model endpoint reported insufficient_user_quota; "
                            "account details omitted."
                        )
                        line = json.dumps(record, ensure_ascii=False)
                    lines.append(line)
                logs.append({"name": path.name, "text": "\n".join(lines)})
        agents[name] = {
            "label": "MiniAgent" if name == "miniagent" else "Claude Code",
            "targetModel": result["config"]["agent"]["llm"]["model_name"],
            "workerModel": result["config"]["algorithm"]["worker"]["llm"]["model_name"],
            "splits": result["split_counts"],
            "initialDev": next(
                row["hard"] for row in evaluations if row["stage"] == "baseline"
            ),
            "accepted": result["accepted_candidates"],
            "decisions": decisions,
            "evaluations": [
                {k: row[k] for k in ("stage", "tasks", "finished", "hard", "f1")}
                for row in evaluations
                if row["stage"] not in {"initial-test", "final-test"}
            ],
            "logs": logs,
        }
    # Only selected display fields are exported. Configs and model connection settings
    # stay private; refuse to emit credential-shaped strings in any preserved text.
    data = {
        "schemaVersion": 1,
        "algorithm": "SkillOpt",
        "benchmark": "SearchQA",
        "date": "2026-09-19–20",
        "dateLabel": "19–20 Sep 2026",
        "seed": 42,
        "dataset": "SearchQA · supplied-context QA",
        "description": "A historical adaptation run of SkillOpt within FlashRSI, rather than a reproduction of the original paper's setup.",
        "metric": "Official hard score (normalized EM with answer extraction)",
        "agents": agents,
    }
    encoded = json.dumps(data, ensure_ascii=False)
    if re.search(
        r"(?:sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
        encoded,
    ):
        raise ValueError(
            "Credential-shaped content found; review the source before exporting"
        )
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = export(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"Exported {sum(len(agent['decisions']) for agent in data['agents'].values())} candidate decisions without test results."
    )
