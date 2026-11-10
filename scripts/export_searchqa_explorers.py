"""Export selection-focused website data from reduced historical QA records.

Input contains records/<algorithm>-<harness>.json and, for DarwinX, records-full/
with its earlier search history. These reduced records retain algorithm events,
non-test evaluations, and deduplicated resource text, rather than model messages.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean

import yaml

METHODS = {
    "opro": (
        "OPRO",
        "Optimization history",
        "Each proposal starts from the fixed seed. The final prompt is selected from the recorded optimization history; entering history is not an incumbent update.",
    ),
    "evoprompt": (
        "EvoPrompt",
        "Population arena",
        "These archived runs use differential evolution. Each trial competes with its own population slot, and ties retain the target. Final promotion is separate from slot replacement.",
    ),
    "gepa": (
        "GEPA",
        "Coverage frontier",
        "Parent choice and final selection are different: the recorded population preserves per-task scores and ancestry, while final promotion selects a population member by mean score.",
    ),
    "ace": (
        "ACE",
        "Playbook ledger",
        "Curator updates advance a playbook without requiring an immediate dev improvement. Periodic validation and final checkpoint promotion are shown separately.",
    ),
    "ahe": (
        "AHE",
        "Repair audit",
        "Repair decisions include file-level predicted fixes, realized regressions, and recorded file-audit verdicts. The historical final dev selection is a separate phase, not a per-edit acceptance rule.",
    ),
    "adas": (
        "ADAS",
        "Design archive",
        "Admitting an evaluated design to the archive does not mean it is the best design. Read the design account, inspect its resources, and compare the final archived selection.",
    ),
    "meta_harness": (
        "Meta-Harness",
        "Experiment notebook",
        "The search records training experiments and earlier versions. Its historical final selection evaluates archived candidates on dev after that search, rather than selecting every edit by dev.",
    ),
    "darwinx": (
        "DarwinX",
        "Branch admission",
        "Original screen/confirmation decisions and the later fixed-archive dev-gate reselection are distinct phases. The reselection generated no new proposals; its gates still constrain the winner.",
    ),
    "modular_rsi": (
        "ModularRSI",
        "Branches and integration",
        "Independent module branches pass review and execution gates before integration. Execution success is not answer correctness; the final dev selection is recorded separately.",
    ),
    "rrsi": (
        "RRSI",
        "Round tournament",
        "These runs select the native incumbent using calibrated uncertainty, gain/cost budgets, admissibility checks, and competition between variants. Dev was not used for selection.",
    ),
    "evoharness": (
        "Evo-Harness",
        "Skill production",
        "These runs compile and organize reusable topic/general skills while processing a training stream. They do not select a best-dev checkpoint. The terminal skill library is the selected artifact.",
    ),
}


def take(value, keys):
    return {key: value[key] for key in keys if key in value}


def metric(record, score_key="hard"):
    rows = record.get("per_task")
    if not isinstance(rows, list) or not rows:
        return None
    scores = [row.get("metrics", {}).get(score_key) for row in rows]
    return mean(scores) if all(isinstance(x, (int, float)) for x in scores) else None


def build(raw, key, harness, benchmark="searchqa"):
    records = raw["records"]
    meta = raw.get("meta") or {}
    if key == "evoharness":
        run = meta["run_dir"].rsplit("/", 1)[-1]
        records = [row for row in records if f"/{run}/" in row["source"]]
    configs = [yaml.safe_load(value) for value in raw["configs"].values()]
    config = next((value for value in configs if isinstance(value, dict)), {})
    algorithm_config = config.get("algorithm", {})
    selected = (
        meta.get("final_snapshot")
        or meta.get("selected_snapshot")
        or meta.get("snapshot_id")
    )
    initial = meta.get("initial_snapshot")
    if not initial:
        initial = next(
            row["data"]["snapshot_id"] for row in records if "baseline" in row["name"]
        )
    assert selected in raw["snapshots"] and initial in raw["snapshots"], (
        key,
        harness,
        "missing selected/initial resource version",
    )
    states = raw["snapshots"]

    def signature(snapshot):
        return {
            path: (entry["ref"], entry.get("executable", False))
            for path, entry in states.get(snapshot, {}).get("files", {}).items()
        }

    selected_files = signature(selected)

    def node(snapshot, **extra):
        return {
            "id": snapshot,
            "selected": snapshot == selected,
            "finalContent": bool(
                snapshot in states and signature(snapshot) == selected_files
            ),
            **extra,
        }

    evaluations = []
    for row in records:
        value = row["data"]
        if not isinstance(value, dict) or not isinstance(value.get("per_task"), list):
            continue
        if key == "rrsi" and row["name"].endswith(
            ("initial-dev.json", "final-dev.json")
        ):
            continue
        evaluations.append(
            {
                "record": row["name"],
                "stage": re.sub(r"^\d+-", "", row["name"]).removesuffix(".json"),
                "id": value.get("snapshot_id"),
                "tasks": len(value["per_task"]),
                "score": metric(
                    value, "exact_match" if benchmark == "hotpotqa" else "hard"
                ),
            }
        )
    decisions = [
        row["data"] for row in records if row["name"].endswith("decision.json")
    ]
    promotions = [row for row in decisions if row.get("kind") == "promote"]
    promotion = next(
        (row for row in promotions if row.get("candidate_id") == selected),
        promotions[-1] if promotions else {},
    )

    def dev_selection():
        rows = promotion.get("dev_scores")
        if rows:
            return [node(row["snapshot_id"], score=row["dev_score"]) for row in rows]
        return [
            node(row["id"], score=row["score"])
            for row in evaluations
            if row["stage"] == "selection-dev"
        ]

    method = {}
    if key == "opro":
        history = promotion["history"]
        method = {
            "history": [
                node(row["snapshot_id"], number=i, score=row["score"], text=row["text"])
                for i, row in enumerate(history)
            ],
            "optimizationTasks": evaluations[0]["tasks"],
            "split": "train",
        }
    elif key == "evoprompt":
        prior = [
            node(row["id"], score=row["score"])
            for row in evaluations
            if row["stage"] in {"baseline", "seed"}
        ]
        generations = []
        for row in decisions:
            if row.get("kind") != "generation":
                continue
            slots = []
            for index, (target, trial, survivor) in enumerate(
                zip(prior, row["candidates"], row["population"], strict=True)
            ):
                assert survivor["snapshot_id"] in {target["id"], trial["snapshot_id"]}
                assert survivor["score"] == max(target["score"], trial["score"])
                if target["score"] == trial["score"]:
                    assert survivor["snapshot_id"] == target["id"]
                slots.append(
                    {
                        "slot": index + 1,
                        "target": target,
                        "trial": node(trial["snapshot_id"], score=trial["score"]),
                        "survivor": node(
                            survivor["snapshot_id"], score=survivor["score"]
                        ),
                        "replaced": survivor["snapshot_id"] == trial["snapshot_id"],
                    }
                )
            generations.append(
                {"step": row["step"], "variant": row["variant"], "slots": slots}
            )
            prior = [
                node(item["snapshot_id"], score=item["score"])
                for item in row["population"]
            ]
        method = {
            "generations": generations,
            "finalPopulation": prior,
            "optimizationTasks": evaluations[0]["tasks"],
        }
    elif key == "gepa":
        population = promotion["population"]
        task_ids = list(population[0]["per_task"])
        best = {
            task: max(row["per_task"][task] for row in population) for task in task_ids
        }
        members = []
        for row in population:
            covered = [row["per_task"][task] == best[task] for task in task_ids]
            members.append(
                node(
                    row["snapshot_id"],
                    index=row["index"],
                    parents=row["parents"],
                    score=row["score"],
                    text=row["text"],
                    coverage=covered,
                    coverageWins=sum(covered),
                )
            )
        method = {
            "population": members,
            "tasks": len(task_ids),
            "metricCalls": promotion["metric_calls"],
            "iterations": promotion["iterations"],
            "parentChoices": [
                take(
                    row,
                    [
                        "iteration",
                        "parent_index",
                        "kind",
                        "reason",
                        "parent_score",
                        "score",
                        "accepted",
                    ],
                )
                for row in decisions
                if "iteration" in row
            ],
        }
    elif key == "ace":
        updates = [row for row in decisions if row.get("kind") == "curate"]
        chain = []
        for i, row in enumerate(updates):
            changed = [
                path
                for path in signature(row["candidate_id"])
                if signature(row["candidate_id"])[path]
                != signature(row["parent_id"]).get(path)
            ]
            chars = sum(
                len(raw["resources"][states[row["candidate_id"]]["files"][path]["ref"]])
                for path in changed
            )
            chain.append(
                node(
                    row["candidate_id"],
                    number=i + 1,
                    parent=row["parent_id"],
                    paths=changed,
                    changedTextChars=chars,
                )
            )
        method = {
            "updates": chain,
            "checkpoints": [
                node(row["id"], score=row["score"], record=row["record"])
                for row in evaluations
                if row["stage"] == "validation"
            ],
            "declined": sum(row["name"].endswith("declined.json") for row in records),
            "promotionScore": promotion.get("score"),
        }
    elif key == "ahe":
        repairs = []
        for row in decisions:
            if "step" not in row:
                continue
            repairs.append(
                {
                    **take(
                        row,
                        [
                            "step",
                            "kind",
                            "accepted",
                            "parent_score",
                            "candidate_score",
                            "manifest",
                            "changes",
                            "unattributed_regressions",
                        ],
                    ),
                    "node": node(row["candidate_id"]),
                    "parent": row["parent_id"],
                }
            )
        method = {"repairs": repairs, "selection": dev_selection()}
    elif key == "adas":
        revisions = {}
        pending = []
        for event in records:
            output = event["data"].get("worker_output")
            if isinstance(output, str):
                design = re.search(r"<DESIGN>(.*?)</DESIGN>", output, re.S)
                if design:
                    pending.append(design.group(1).strip())
            if event["data"].get("kind") == "admit":
                revisions[event["data"]["candidate_id"]] = pending
                pending = []
        archive = []
        seed = next(row for row in evaluations if row["stage"] == "seed")
        archive.append(
            node(
                initial,
                number=0,
                score=seed["score"],
                account="The harness this run started from",
            )
        )
        for row in decisions:
            if row.get("kind") == "admit":
                archive.append(
                    node(
                        row["candidate_id"],
                        number=len(archive),
                        score=row["candidate_score"],
                        parent=row["parent_id"],
                        account=row.get("account", ""),
                        revisions=revisions.get(row["candidate_id"], []),
                        admitted=row.get("accepted"),
                    )
                )
        method = {"archive": archive, "promotionScore": promotion.get("score")}
    elif key == "meta_harness":
        notes = {}
        latest_note = ""
        for event in records:
            output = event["data"].get("worker_output")
            if isinstance(output, str):
                latest_note = output[:7000]
            if event["data"].get("kind") == "admit":
                notes[event["data"]["candidate_id"]] = latest_note
        trials = []
        for row in decisions:
            if row.get("kind") == "admit":
                trials.append(
                    {
                        **take(row, ["step", "score", "split"]),
                        "node": node(row["candidate_id"]),
                        "parent": row["parent_id"],
                        "workerNoteExcerpt": notes.get(row["candidate_id"], ""),
                    }
                )
        method = {
            "trials": trials,
            "selection": dev_selection(),
            "initialTrain": next(
                (
                    row["data"]["score"]
                    for row in records
                    if row["name"].endswith("scores.json")
                ),
                None,
            ),
        }
    elif key == "darwinx":
        original = []
        for row in decisions:
            if "fidelity" in row and "snapshot_id" in row:
                original.append(
                    {
                        **take(
                            row,
                            [
                                "step",
                                "kind",
                                "parent_id",
                                "donor_id",
                                "fidelity",
                                "samples",
                                "score",
                                "accepted",
                                "gain",
                                "cumulative_gain",
                                "regression_mass",
                                "lost_invariant",
                                "account",
                            ],
                        ),
                        "node": node(row["snapshot_id"]),
                    }
                )
        gates = [
            take(
                row["data"],
                [
                    "step",
                    "snapshot_id",
                    "parent_id",
                    "donor_id",
                    "gain",
                    "regression_mass",
                    "delta",
                    "accepted",
                    "samples",
                    "hard_invariant_veto",
                    "gate_split",
                ],
            )
            for row in records
            if "reselection-gate" in row["name"]
        ]
        if not gates:
            gates = promotion.get("gates", [])
        dev = [
            node(row["id"], score=row["score"])
            for row in evaluations
            if row["stage"] == "reselection-dev"
        ]
        if not dev:
            dev = [
                node(row["snapshot_id"], score=row["dev_score"])
                for row in promotion.get("dev_scores", [])
            ]
        selection_rows = promotion.get("dev_scores", [])
        eligible_ids = {
            row["snapshot_id"]
            for row in selection_rows
            if row.get("gate_admitted", True)
        }
        method = {
            "original": original,
            "gates": gates,
            "dev": dev,
            "eligible": [row for row in dev_selection() if row["id"] in eligible_ids]
            if selection_rows
            else dev_selection(),
            "newProposals": meta.get("new_proposals"),
            "mode": meta.get("mode", "search_then_dev_gate_selection"),
        }
    elif key == "modular_rsi":
        branches = []
        module_promotion = next(
            (row for row in reversed(promotions) if "modules" in row), promotion
        )
        for name, version in module_promotion["modules"].items():
            branch_events = [row for row in decisions if row.get("module") == name]
            branches.append(
                {
                    "name": name,
                    "version": version,
                    "events": [
                        take(
                            row,
                            ["kind", "parent_id", "candidate_id", "problem", "reason"],
                        )
                        for row in branch_events
                    ],
                }
            )
        reviews = [
            take(row["data"], ["module", "candidate_id", "accept", "reason"])
            for row in records
            if row["name"].endswith("review.json")
        ]
        gates = [
            row["data"]
            for row in records
            if row["name"].endswith("-gate.json")
            and "execution_gate" not in row["name"]
        ]
        method = {
            "branches": branches,
            "reviews": reviews,
            "gates": [
                take(
                    row,
                    [
                        "module",
                        "snapshot_id",
                        "candidate_id",
                        "passed",
                        "status",
                        "problem",
                        "reason",
                    ],
                )
                for row in gates
            ],
            "integration": [
                take(
                    row,
                    [
                        "kind",
                        "module",
                        "parent_id",
                        "candidate_id",
                        "problem",
                        "reason",
                    ],
                )
                for row in decisions
                if "integration" in row.get("kind", "")
                or row.get("module") == "integration"
            ],
            "selection": dev_selection(),
        }
    elif key == "rrsi":
        calibration = next(
            row["data"] for row in records if row["name"].endswith("calibration.json")
        )
        contexts = [
            row["data"] for row in records if row["name"].endswith("rrsi-context.json")
        ]
        history = [
            row["data"] for row in records if row["name"].endswith("edit-history.json")
        ]
        rounds = []
        for i, context in enumerate(contexts):
            entries = [
                take(
                    row,
                    [
                        "t",
                        "variant",
                        "id",
                        "component",
                        "paths",
                        "operation",
                        "targets_mode",
                        "hypothesis",
                        "parent_id",
                        "candidate_id",
                        "admissible",
                        "reason",
                        "delta_S",
                        "delta_C",
                        "accepted",
                        "outcome",
                        "guards",
                        "novelty",
                    ],
                )
                for row in history
                if row["t"] == context["step"]
            ]
            rounds.append(
                {
                    **take(
                        context,
                        [
                            "step",
                            "incumbent_id",
                            "score",
                            "cost",
                            "best_score",
                            "delta",
                            "budget",
                            "stalled",
                            "untried",
                            "prune",
                        ],
                    ),
                    "nextIncumbent": contexts[i + 1]["incumbent_id"]
                    if i + 1 < len(contexts)
                    else selected,
                    "edits": entries,
                }
            )
        method = {
            "calibration": calibration,
            "rounds": rounds,
            "smokeGates": [
                take(row["data"], ["snapshot_id", "passed", "stage", "task_ids"])
                for row in records
                if row["name"].endswith("smoke-gate.json")
            ],
            "measurements": [
                take(row["data"], ["snapshot_id", "score", "cost", "guard_metrics"])
                for row in records
                if row["name"].endswith("measurement.json")
            ],
            "parameters": take(
                algorithm_config,
                [
                    "T",
                    "k",
                    "m",
                    "b_min",
                    "b_max",
                    "w",
                    "beta0",
                    "beta1",
                    "w_s",
                    "w_c",
                    "w_n",
                ],
            ),
            "promotion": take(promotion, ["score", "cost", "best_score", "delta"]),
        }
    elif key == "evoharness":
        operations = [
            row["data"]
            for row in records
            if row["name"].endswith(("decision.json", "declined.json"))
        ]
        operations = [row for row in operations if row.get("kind") != "stream"]
        terminal = next(row for row in decisions if row.get("kind") == "stream")
        levels = {}
        for operation in operations:
            if operation.get("accepted"):
                for path in operation.get("changed_paths", []):
                    levels[path] = operation.get("level", "unclassified")
        library = [
            {
                "path": path,
                "level": levels.get(path, "seed / unclassified"),
                "chars": len(raw["resources"][entry["ref"]]),
            }
            for path, entry in states[selected]["files"].items()
            if path.startswith("skills/") and path.endswith("SKILL.md")
        ]
        method = {
            "library": library,
            "operations": [
                take(
                    row,
                    [
                        "kind",
                        "level",
                        "step",
                        "parent_id",
                        "candidate_id",
                        "accepted",
                        "changed_paths",
                        "problem",
                    ],
                )
                for row in operations
            ],
            "terminal": take(terminal, ["snapshot_id", "online_score", "online_tasks"]),
            "batchSize": algorithm_config.get("batch_size"),
            "levels": dict(
                Counter(row.get("level", "unclassified") for row in operations)
            ),
        }

    # A common ledger retains facts without giving every method a keep/reject policy.
    ledger_keys = [
        "kind",
        "step",
        "iteration",
        "module",
        "component",
        "level",
        "parent_id",
        "candidate_id",
        "snapshot_id",
        "accepted",
        "admissible",
        "passed",
        "reason",
        "problem",
        "score",
        "parent_score",
        "candidate_score",
        "cost",
        "gain",
        "regression_mass",
        "delta",
        "outcome",
        "split",
        "selection_split",
        "evolution_split",
    ]
    events = []
    for row in records:
        if row["name"].endswith(
            (
                "decision.json",
                "declined.json",
                "edit-history.json",
                "calibration.json",
                "smoke-gate.json",
                "reselection-gate.json",
                "review.json",
            )
        ):
            events.append(
                {"record": row["name"], "details": take(row["data"], ledger_keys)}
            )

    changed = set()
    base_files = signature(initial)
    for version in states:
        files = signature(version)
        changed.update(
            path
            for path in base_files.keys() | files.keys()
            if base_files.get(path) != files.get(path)
        )
    public_states = {}
    text_refs = set()
    for version, state in states.items():
        files = {
            path: entry["ref"]
            for path, entry in state["files"].items()
            if path in changed
        }
        text_refs.update(files.values())
        public_states[version] = {"parent": state["parent_id"], "files": files}
        public_states[version]["executable"] = {
            path: entry.get("executable", False)
            for path, entry in state["files"].items()
            if path in changed
        }
    resources = {
        "initialId": initial,
        "selectedId": selected,
        "states": public_states,
        "texts": {ref: raw["resources"][ref] for ref in sorted(text_refs)},
    }
    model = config.get("agent", {}).get("llm", {})
    worker = algorithm_config.get("worker", {}).get("llm", {})
    agent = {
        "label": "MiniAgent" if harness == "miniagent" else "Claude Code",
        "initialId": initial,
        "selectedId": selected,
        "targetModel": model.get("model_name", "Not recorded"),
        "workerModel": worker.get("model_name", "Not recorded"),
        "method": method,
        "evaluations": evaluations,
        "events": events,
        "changedPaths": sorted(changed),
        "resourcesPath": f"/experiment-data/{benchmark}/resources/{key}-{harness}.json",
    }
    return agent, resources


def write(path, data):
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if re.search(
        r"(?:sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
        text,
    ):
        raise ValueError(
            f"Credential-shaped text in {path.name}; review before publishing"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--benchmark", choices=("searchqa", "hotpotqa"), default="searchqa"
    )
    args = parser.parse_args()
    for key, (label, lens, rule) in METHODS.items():
        agents = {}
        for harness in ["miniagent", "claude_code"]:
            path = args.records / "records" / f"{key}-{harness}.json"
            if key == "darwinx" and args.benchmark == "searchqa":
                path = args.records / "records-full" / path.name
            with path.open(encoding="utf-8") as stream:
                raw = json.load(stream)
            agent, resources = build(raw, key, harness, args.benchmark)
            agents[harness] = agent
            write(args.output / "resources" / f"{key}-{harness}.json", resources)
            print(
                f"{key}/{harness}: {len(agent['events'])} events, {len(agent['evaluations'])} non-test evaluations, {len(agent['changedPaths'])} resource paths"
            )
        write(
            args.output / f"{key}.json",
            {
                "schemaVersion": 2,
                "key": key,
                "algorithm": label,
                "benchmark": "HotpotQA" if args.benchmark == "hotpotqa" else "SearchQA",
                "lens": lens,
                "selectionRule": (
                    "Original screen/confirmation decisions, the recorded dev gates, and final selection are distinct phases. This run selected from the searched archive after evolution."
                    if args.benchmark == "hotpotqa" and key == "darwinx"
                    else rule
                ),
                "agents": agents,
            },
        )


if __name__ == "__main__":
    main()
