"""Map archived agentic benchmark records to evolution views and resource diffs."""

import json
import re
from copy import deepcopy

from export_searchqa_explorers import METHODS, build, take

LABELS = {k: (label, lens) for k, (label, lens, _) in METHODS.items()}
LABELS["skillopt"] = ("SkillOpt", "Fast / slow skill updates")
RULES = {
    "skillopt": "Fast and slow skill proposals retain their recorded acceptance decisions. Final selection is marked separately.",
    "opro": "Compare the scored prompt history and its recorded final selection.",
    "evoprompt": "Generations preserve proposed prompts and the surviving population. Slot replacement and final selection are distinct.",
    "gepa": "Per-task coverage guides population search and parent sampling. Highlighting follows the recorded final artifact.",
    "ace": "Curator edits advance the playbook. Validation checkpoints and the final playbook are displayed separately.",
    "ahe": "Inspect predicted fixes, realized risks, file verdicts, and repair decisions alongside final selection.",
    "adas": "Designs enter an evaluation archive. Pruning, archive admission, and final selection retain their recorded outcomes.",
    "meta_harness": "Measured harness experiments form a notebook. The recorded final selection chooses from that history.",
    "darwinx": "Branches pass screening and confirmation with gain, regression, and invariant gates. Final selection follows the recorded artifact.",
    "modular_rsi": "Module branches undergo review and execution checks before integration. The recorded final version is highlighted separately.",
    "rrsi": "Variants compete within rounds under calibrated uncertainty and gain/cost budgets. Admissibility and round outcomes are kept distinct.",
    "evoharness": "Online experience produces topic and general skills. Applied, declined, and no-op proposals lead to the terminal library.",
}
FIELDS = "step epoch iteration kind variant t component parent_id candidate_id snapshot_id donor_id accepted outcome score baseline_score parent_score candidate_score dev_score reason problem account fidelity samples gain cumulative_gain regression_mass lost_invariant delta hard_invariant_veto gate_split delta_S delta_C admissible hypothesis paths guards novelty operation targets_mode module accept passed status level changed_paths manifest changes unattributed_regressions selection selection_policy selection_split dev_used_for_selection budget stalled incumbent_id incumbent_score incumbent_cost cost metric_calls iterations parent_index evaluation compile_level online_tasks online_score batch_size source retained path text name thought fitness".split()


def export_run(raw, key, harness, benchmark="terminalbench"):
    raw = deepcopy(raw)
    meta = raw.get("meta") or {}
    records = raw["records"]
    attempt = (meta.get("attempt") or "").rsplit("/", 1)[-1]
    if key in {"skillopt", "opro", "evoprompt", "adas", "gepa", "ahe", "meta_harness"}:
        matched = [
            r for r in records if attempt and f"/{attempt}/" in "/" + r["source"]
        ]
        # Some AppWorld summaries name a later continuation; use the archived
        # promotion's own directory rather than mixing another harness's history.
        if not matched and benchmark == "appworld":
            selected = (
                meta.get("final_snapshot")
                or meta.get("selected_snapshot")
                or meta.get("snapshot_id")
            )
            prefixes = [
                r["source"].split("/trajectories/")[0]
                for r in records
                if r["data"].get("kind") == "promote"
                and r["data"].get("candidate_id") == selected
                and f"{key}-{harness}-" in r["source"]
            ]
            if prefixes:
                prefix = max(
                    prefixes,
                    key=lambda p: sum(r["source"].startswith(p + "/") for r in records),
                )
                matched = [r for r in records if r["source"].startswith(prefix + "/")]
                configs = {
                    p: v
                    for p, v in raw["configs"].items()
                    if p.startswith(prefix + "/")
                }
                if configs:
                    raw["configs"] = configs
        if matched:
            records = matched
    if key == "ace":
        records = sorted(
            records, key=lambda r: ("history/" not in r["source"], r["source"])
        )
    if key == "evoharness" and meta.get("run_dir"):
        run = meta["run_dir"].rsplit("/", 1)[-1]
        records = [r for r in records if f"/{run}/" in r["source"]]
    raw["records"] = records
    if benchmark == "appworld":
        # Archives can also contain another harness's saved training history.
        # Keep the target lineage and versions explicitly used by its records.
        versions = {
            value
            for value in (
                meta.get("initial_snapshot"),
                meta.get("final_snapshot")
                or meta.get("selected_snapshot")
                or meta.get("snapshot_id"),
            )
            if isinstance(value, str)
        }
        for row in records:
            versions.update(
                value
                for field in (
                    "snapshot_id",
                    "candidate_id",
                    "parent_id",
                    "incumbent_id",
                )
                if isinstance(value := row["data"].get(field), str)
            )
        while True:
            expanded = versions | {
                identifier
                for identifier, state in raw["snapshots"].items()
                if state.get("parent_id") in versions
            }
            expanded.update(
                parent
                for identifier in versions
                if isinstance(
                    parent := raw["snapshots"].get(identifier, {}).get("parent_id"), str
                )
            )
            if expanded == versions:
                break
            versions = expanded
        raw["snapshots"] = {
            identifier: state
            for identifier, state in raw["snapshots"].items()
            if identifier in versions
        }
    agent, resources = build(
        raw,
        "artifact",
        harness,
        benchmark=benchmark,
        metric_key="reward",
        resource_prefix=f"/experiment-data/{benchmark}",
    )
    agent["resourcesPath"] = (
        f"/experiment-data/{benchmark}/resources/{key}-{harness}.json"
    )
    agent["preservedVersions"] = list(resources["states"])
    agent.pop("method")
    decisions = [r for r in records if r["name"].endswith("decision.json")]
    promotions = [r["data"] for r in decisions if r["data"].get("kind") == "promote"]
    selected = agent["selectedId"]
    promotion = next(
        (r for r in reversed(promotions) if r.get("candidate_id") == selected),
        take(meta, FIELDS),
    )

    def node(version, **details):
        return {"id": version, "selected": version == selected, **details}

    entries, seen = [], set()
    for row in decisions:
        d = row["data"]
        identity = json.dumps(d, sort_keys=True)
        if identity in seen or d.get("kind") == "promote":
            continue
        seen.add(identity)
        item = node(
            d.get("candidate_id") or d.get("snapshot_id"),
            number=len(entries) + 1,
            record=row["name"],
            **take(d, FIELDS),
        )
        if key == "skillopt" and d.get("patch"):
            item["explanation"] = d["patch"].get("reasoning")
        entries.append(item)
    final = [
        node(r["snapshot_id"], score=r["dev_score"], gate=r.get("gate_admitted"))
        for r in promotion.get("dev_scores", [])
    ]
    split = promotion.get("selection_split") or meta.get("selection_split")
    if not final:
        final = [
            node(r["id"], score=r["score"])
            for r in agent["evaluations"]
            if "selection-dev" in r["stage"]
        ]
        if final:
            split = "dev"
    if not final and key == "meta_harness":
        final = [
            node(
                agent["initialId"],
                score=next(
                    (
                        r["score"]
                        for r in agent["evaluations"]
                        if "baseline" in r["stage"] or "seed" in r["stage"]
                    ),
                    None,
                ),
            )
        ]
        final.extend(
            node(r["id"], score=r.get("score"))
            for r in entries
            if r.get("kind") in {"experiment", "admit"}
        )
        split = "train"
    selection_note = None
    if (
        benchmark == "appworld"
        and meta.get("selection_kind") == "explicit_user_override"
    ):
        # Saved artifact selection and automatic gate admission are separate.
        # Keep the original decisions; never manufacture a dev score for adoption.
        native_promotion = promotions[-1]
        promotion = {
            "kind": "artifact_selection",
            "candidate_id": selected,
            "selection": "archived_user_frozen_version",
            "original_algorithm_selected_id": native_promotion["candidate_id"],
        }
        for row in final:
            row["selected"] = row["id"] == selected
        if not any(row["id"] == selected for row in final):
            final.append(node(selected))
        selection_note = (
            "The selected artifact follows the archived user-frozen version. "
            "The original algorithm decision and gate outcomes are preserved."
        )
    evolution = {
        "key": key,
        "entries": entries,
        "finalSelection": final,
        "finalLabel": split.title() + " score" if split else "Recorded score",
        "promotion": take(promotion, FIELDS),
        "history": [],
        "generations": [],
        "population": [],
        "modules": [],
        "contexts": [],
        "edits": [],
        "operations": [],
        "playbooks": [],
        "designs": [],
        "gates": promotion.get("gates", []),
        "checkpoints": [
            node(r["id"], score=r["score"])
            for r in agent["evaluations"]
            if "validation" in r["stage"]
        ],
    }
    if selection_note:
        evolution["promotion"] = promotion
        evolution["algorithmPromotion"] = take(native_promotion, FIELDS)
        evolution["selectionNote"] = selection_note
    if key == "opro":
        history = next((r["history"] for r in promotions if r.get("history")), [])
        evolution["history"] = [
            node(
                r["snapshot_id"], number=i, score=r.get("score"), text=r.get("text", "")
            )
            for i, r in enumerate(history)
        ]
    if key == "evoprompt":
        evolution["generations"] = [
            {
                **take(r["data"], FIELDS),
                "population": r["data"].get("population", []),
                "proposals": r["data"].get(
                    "candidates", r["data"].get("proposals", [])
                ),
            }
            for r in decisions
            if r["data"].get("kind") == "generation"
        ]
    if key == "gepa":
        population = next(
            (r["population"] for r in promotions if r.get("population")), []
        )
        tasks = list(population[0].get("per_task", {})) if population else []
        best = {t: max(p["per_task"][t] for p in population) for t in tasks}
        evolution["population"] = [
            node(
                p["snapshot_id"],
                index=p["index"],
                score=p.get("score"),
                parents=p.get("parents", []),
                text=p.get("text", ""),
                coverage=[p["per_task"][t] == best[t] for t in tasks],
            )
            for p in population
        ]
    if key == "ace":
        evolution["playbooks"] = [
            r for r in entries if r.get("kind") in {"curate", "tally"}
        ]
    if key == "adas":
        drafts = []
        for row in records:
            reply = row["data"].get("worker_output")
            if isinstance(reply, str):
                design = re.search(r"<DESIGN>(.*?)</DESIGN>", reply, re.S)
                if design:
                    drafts.append(design.group(1).strip())
            if row["name"].endswith("decision.json") and row["data"].get("kind") in {
                "admit",
                "upper_bound_pruned",
            }:
                entry = next((r for r in entries if r["record"] == row["name"]), None)
                if entry is not None and drafts:
                    entry["drafts"] = drafts
                    entry.setdefault("account", drafts[-1])
                drafts = []
        evolution["designs"] = [
            r
            for r in entries
            if r.get("kind") in {"admit", "upper_bound_pruned", "decline", "declined"}
        ]
    if key == "modular_rsi":
        names = list(
            dict.fromkeys(
                r.get("module")
                for r in entries
                if r.get("module") and r.get("module") != "integration"
            )
        )
        evolution["modules"] = [
            {"name": name, "entries": [r for r in entries if r.get("module") == name]}
            for name in names
        ]
        evolution["gates"] = [
            take(r["data"], FIELDS)
            for r in records
            if r["name"].endswith(("review.json", "gate.json"))
        ]
    if key == "rrsi":
        evolution["contexts"] = [
            take(r["data"], FIELDS)
            for r in records
            if r["name"].endswith("rrsi-context.json")
        ]
        evolution["edits"] = [
            take(r["data"], FIELDS)
            for r in records
            if r["name"].endswith("edit-history.json")
        ]
        evolution["calibration"] = next(
            (
                take(r["data"], FIELDS)
                for r in records
                if r["name"].endswith("calibration.json")
            ),
            {},
        )
    if key == "evoharness":
        evolution["operations"] = [
            take(r["data"], FIELDS)
            for r in records
            if r["data"].get("kind") in {"compile", "organize", "stream"}
            or r["name"].endswith("declined.json")
        ]
    agent["evolution"] = evolution
    agent["events"] = [
        {"record": r["name"], "details": take(r["data"], FIELDS)}
        for r in records
        if r["name"].endswith(
            (
                "decision.json",
                "review.json",
                "gate.json",
                "edit-history.json",
                "calibration.json",
            )
        )
    ]
    return agent, resources
