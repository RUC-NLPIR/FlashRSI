"""Read-only, fixed-manifest PREFIX audit; never invoke an Agent or load .env.

Only this script's own timestamped output directory is written. Runtime files,
cache records, snapshots, and trajectory aggregates are opened read-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from flashrsi._records import _config_record  # noqa: E402
from flashrsi.core import Snapshot  # noqa: E402
from scripts._experiment_runtime import _digest  # noqa: E402

RUN = ROOT / "runs/skillopt-searchqa-deepseek/full"
OUTPUT_ROOT = RUN / "evidence"
HARNESSES = ("miniagent", "claude_code")
FLASH = "deepseek-v4-flash"
PRO = "deepseek-v4-pro"
SKILL = "flashrsi:searchqa"


def sha(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def relative(path):
    return str(path.relative_to(ROOT))


def freeze_manifest():
    cutoff_ns = time.time_ns()
    cutoff = datetime.fromtimestamp(cutoff_ns / 1e9, timezone.utc)
    out = OUTPUT_ROOT / ("native-model-prefix-" + cutoff.strftime("%Y%m%dT%H%M%S.%fZ"))
    out.mkdir(parents=True)
    entries = []
    for harness in HARNESSES:
        base = RUN / harness
        groups = {
            "plan": [base / "plan.json"],
            "target": sorted((base / "cache/target" / harness).glob("*.json")),
            "worker": sorted((base / "cache/worker/llm").glob("*.json")),
            "snapshots": sorted(base.glob("attempts/*/snapshots/*.json")),
            "aggregates": sorted(base.glob("attempts/*/trajectories/*.json")),
            "auxiliary_error_artifacts": sorted(base.glob("cache/errors/*/*/*.json")),
        }
        for group, paths in groups.items():
            for path in paths:
                stat = path.stat()
                if stat.st_mtime_ns <= cutoff_ns:
                    entries.append(
                        {
                            "path": relative(path),
                            "harness": harness,
                            "group": group,
                            "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                        }
                    )
    manifest = {
        "audit_kind": "prefix",
        "cutoff_utc": cutoff.isoformat(),
        "cutoff_ns": cutoff_ns,
        "root": str(ROOT),
        "files": entries,
    }
    dump(out / "manifest.json", manifest)
    return out, manifest


def stable_bytes(entry):
    path = ROOT / entry["path"]
    before = path.stat()
    expected = (entry["size"], entry["mtime_ns"])
    if (before.st_size, before.st_mtime_ns) != expected:
        raise ValueError("file_changed_since_manifest")
    data = path.read_bytes()
    after = path.stat()
    if (after.st_size, after.st_mtime_ns) != expected:
        raise ValueError("file_changed_during_read")
    return data


def stable_json(entry):
    data = stable_bytes(entry)
    return json.loads(data), sha(data)


def configs(messages):
    return [m for m in messages if m.get("type") == "RunConfig"]


def model_values(values):
    return sorted(set(values), key=lambda x: (x is not None, str(x)))


def check_labels(values, expected, location, reasons):
    if not values or any(value in (None, "") for value in values):
        reasons.append(location + ":missing")
    if any(value not in (None, "", expected) for value in values):
        reasons.append(location + ":mismatch")


def model_audit(harness, role, trajectory):
    messages = trajectory.get("messages", [])
    requested = [
        m.get("config", {}).get("llm", {}).get("model_name") for m in configs(messages)
    ]
    expected = FLASH if role == "target" else PRO
    reasons = []
    check_labels(requested, expected, "RunConfig.config.llm.model_name", reasons)
    evidence = {
        "expected_alias": expected,
        "configured_requested_models": model_values(requested),
        "configured_requested_count": len(requested),
    }
    if role == "worker":
        completions = [m for m in messages if m.get("type") == "ChatCompletion"]
        response = [m.get("model") for m in completions]
        check_labels(response, PRO, "ChatCompletion.model", reasons)
        evidence.update(
            response_reported_models=model_values(response),
            response_count=len(completions),
            completion_finish_reasons=[
                [c.get("finish_reason") for c in m.get("choices", [])]
                for m in completions
            ],
        )
        if not completions or not completions[-1].get("choices"):
            reasons.append("final_ChatCompletion.choices:missing")
        elif any(c.get("finish_reason") != "stop" for c in completions[-1]["choices"]):
            reasons.append("final_ChatCompletion.finish_reason:not_stop")
    elif harness == "miniagent":
        calls = trajectory.get("usage", {}).get("model_calls", [])
        requested_calls = [m.get("model") for m in calls]
        check_labels(requested_calls, FLASH, "usage.model_calls.model", reasons)
        primary = [m for m in calls if m.get("role") == "primary"]
        if not primary:
            reasons.append("usage.model_calls.primary:missing")
        evidence.update(
            requested_call_models=model_values(requested_calls),
            requested_call_count=len(calls),
            primary_call_count=len(primary),
            response_model_evidence="not_recorded_by_miniagent_runtime",
        )
    else:
        init = [
            m.get("data", {}).get("model")
            for m in messages
            if m.get("type") == "SystemMessage" and m.get("subtype") == "init"
        ]
        assistants = [
            m.get("model") for m in messages if m.get("type") == "AssistantMessage"
        ]
        usage = list(trajectory.get("usage", {}).get("model_usage", {}))
        result = [
            key
            for m in messages
            if m.get("type") == "ResultMessage"
            for key in m.get("model_usage", {})
        ]
        for values, location in [
            (init, "SystemMessage.init.data.model"),
            (assistants, "AssistantMessage.model"),
            (usage, "usage.model_usage.keys"),
            (result, "ResultMessage.model_usage.keys"),
        ]:
            check_labels(values, FLASH, location, reasons)
        evidence.update(
            sdk_initialization_models=model_values(init),
            response_reported_models=model_values(assistants),
            assistant_message_count=len(assistants),
            sdk_usage_model_labels=model_values(usage),
            result_usage_model_labels=model_values(result),
        )
    return {
        "status": "consistent" if not reasons else "exception",
        "reasons": reasons,
        **evidence,
    }


def snapshot_info(harness, snapshot):
    files = snapshot.files
    skill_files = sorted(k for k, v in files.items() if v.component == "skill")
    info = {
        "snapshot_id": snapshot.id,
        "agent_type": snapshot.agent_type,
        "skill_component_files": skill_files,
    }
    if harness == "miniagent":
        cfg = yaml.safe_load(files["agent.yaml"].content.decode()) or {}
        names = cfg.get("skills") or []
        refs = [f"skills/{name}.md" for name in names]
        prompt_path = (cfg.get("prompts") or {}).get("system", "prompts/system.md")
        system = files[prompt_path].content.decode()
        blocks = [
            f"\n\n## Skill: {name}\n\n{files[path].content.decode()}"
            for name, path in zip(names, refs)
        ]
        if blocks:
            system = system.rstrip() + "".join(blocks)
        info.update(
            referenced_skill_files=refs,
            unreferenced_skill_component_files=sorted(set(skill_files) - set(refs)),
            expected_system_sha256=sha(system),
            expected_system_chars=len(system),
            _expected_system=system,
            skill_body_chars={p: len(files[p].content.decode().strip()) for p in refs},
        )
    else:
        path = "skills/searchqa/SKILL.md"
        full = files[path].content.decode()
        # Native Skill omits the leading YAML frontmatter from its injected body.
        body = re.sub(
            r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", "", full, count=1, flags=re.DOTALL
        ).strip()
        info.update(
            referenced_skill_files=[path],
            unreferenced_skill_component_files=sorted(set(skill_files) - {path}),
            expected_body_sha256=sha(body),
            expected_body_chars=len(body),
            expected_append_sha256=sha(files["CLAUDE.md"].content),
            _expected_body=body,
            _expected_append=files["CLAUDE.md"].content.decode(),
        )
    return info


def activation_audit(harness, record, info):
    messages = record["trajectory"].get("messages", [])
    if info is None:
        return {"status": "unverified_snapshot", "reasons": ["snapshot_unavailable"]}
    if harness == "miniagent":
        systems = [m.get("content") for m in messages if m.get("role") == "system"]
        refs = info["referenced_skill_files"]
        exact = info["_expected_system"] in systems
        reasons = []
        if not refs:
            reasons.append("no_native_skill_references")
        if any(length == 0 for length in info["skill_body_chars"].values()):
            reasons.append("empty_expected_skill_body")
        if not exact:
            reasons.append("native_composed_system_mismatch_or_missing")
        return {
            "status": "success" if not reasons else "missing_or_mismatch",
            "reasons": reasons,
            "system_message_count": len(systems),
            "exact_native_system_match": exact,
            "referenced_skill_files": refs,
            "expected_system_sha256": info["expected_system_sha256"],
        }

    reasons = []
    inputs = [m for m in messages if m.get("type") == "RunInput"]
    appends = [m.get("system_prompt") for m in inputs]
    append_matches = [
        isinstance(v, dict)
        and v.get("type") == "preset"
        and v.get("preset") == "claude_code"
        and v.get("append") == info["_expected_append"]
        for v in appends
    ]
    if not append_matches or not all(append_matches):
        reasons.append("CLAUDE.md_system_append_mismatch_or_missing")
    if not info["_expected_body"]:
        reasons.append("empty_expected_skill_body")
    calls = []
    expected_calls = []
    final_indices = [
        i
        for i, m in enumerate(messages)
        if m.get("type") == "ResultMessage"
        and m.get("subtype") == "success"
        and m.get("is_error") is False
    ]
    final_index = max(final_indices) if final_indices else -1
    if final_index < 0:
        reasons.append("successful_ResultMessage:missing")
    assistant_text_indices = [
        i
        for i, m in enumerate(messages)
        if m.get("type") == "AssistantMessage"
        and any(
            b.get("type") == "TextBlock" and b.get("text") for b in m.get("content", [])
        )
    ]
    for i, m in enumerate(messages):
        if m.get("type") != "AssistantMessage":
            continue
        for b in m.get("content", []):
            if b.get("type") != "ToolUseBlock" or b.get("name") != "Skill":
                continue
            call = {
                "call_id": b.get("id"),
                "message_index": i,
                "skill": (b.get("input") or {}).get("skill"),
            }
            calls.append(call)
            if call["skill"] != SKILL:
                continue
            results = []
            for j, user in enumerate(messages[i + 1 :], start=i + 1):
                if user.get("type") != "UserMessage":
                    continue
                for result in user.get("content", []):
                    if (
                        result.get("type") != "ToolResultBlock"
                        or result.get("tool_use_id") != call["call_id"]
                    ):
                        continue
                    detail = user.get("tool_use_result") or {}
                    error = (
                        result.get("is_error") is True or detail.get("success") is False
                    )
                    success = (
                        not error
                        and detail.get("success") is True
                        and detail.get("commandName") == SKILL
                    )
                    results.append(
                        {
                            "message_index": j,
                            "error": error,
                            "explicit_success": success,
                        }
                    )
            body_positions = []
            for result in results:
                if not result["explicit_success"] or not info["_expected_body"]:
                    continue
                for k, user in enumerate(
                    messages[result["message_index"] + 1 :],
                    start=result["message_index"] + 1,
                ):
                    if user.get("type") != "UserMessage" or k >= final_index:
                        continue
                    if any(
                        b.get("type") == "TextBlock"
                        and info["_expected_body"] in b.get("text", "")
                        and b.get("text", "").startswith(
                            "Base directory for this skill:"
                        )
                        for b in user.get("content", [])
                    ):
                        if any(k < a < final_index for a in assistant_text_indices):
                            body_positions.append(k)
            call.update(
                results=results, body_message_indices=sorted(set(body_positions))
            )
            expected_calls.append(call)
    error_count = sum(r["error"] for c in expected_calls for r in c["results"])
    success_count = sum(
        r["explicit_success"] for c in expected_calls for r in c["results"]
    )
    chains = sum(bool(c["body_message_indices"]) for c in expected_calls)
    if not expected_calls:
        status = "missing"
        reasons.append("expected_Skill_invocation:missing")
    elif chains:
        status = "success_after_error" if error_count else "success"
    elif error_count and not success_count:
        status = "error"
        reasons.append("expected_Skill_result:error")
    elif success_count:
        status = "body_mismatch_or_unconfirmed"
        reasons.append("successful_Skill_result_without_complete_body_before_answer")
    else:
        status = "result_unconfirmed"
        reasons.append("expected_Skill_result:missing_or_unconfirmed")
    if error_count:
        reasons.append("Skill_error_result_observed")
    if len(calls) > len(expected_calls):
        reasons.append("other_Skill_invocation_observed")
    return {
        "status": status,
        "reasons": reasons,
        "all_Skill_call_count": len(calls),
        "expected_Skill_call_count": len(expected_calls),
        "successful_result_count": success_count,
        "error_result_count": error_count,
        "verified_body_chain_count": chains,
        "calls": calls,
        "exact_CLAUDE_append_match": bool(append_matches) and all(append_matches),
        "expected_body_sha256": info["expected_body_sha256"],
        "expected_body_chars": info["expected_body_chars"],
    }


def stage_index(entries, target_keys, issues):
    index = defaultdict(list)
    attempts = defaultdict(list)
    for e in entries:
        if e["group"] == "aggregates":
            attempts[str(Path(e["path"]).parent)].append(e)
    for directory, rows in sorted(attempts.items()):
        ordinal = 0
        ordinal_reliable = True
        for entry in sorted(rows, key=lambda e: e["path"]):
            try:
                aggregate, _ = stable_json(entry)
            except Exception as error:
                issues.append(
                    {
                        "path": entry["path"],
                        "reason": type(error).__name__ + ":" + str(error)[:150],
                    }
                )
                ordinal_reliable = False
                continue
            if "trajectories" not in aggregate:
                continue
            if not ordinal_reliable:
                continue
            label = Path(entry["path"]).stem.split("-", 1)[1]
            for position, trajectory in enumerate(aggregate["trajectories"]):
                cfgs = configs(trajectory.get("messages", []))
                if len(cfgs) != 1:
                    issues.append(
                        {
                            "path": entry["path"],
                            "position": position,
                            "reason": "target_RunConfig_not_unique",
                        }
                    )
                    continue
                key = _digest(
                    {
                        "version": 2,
                        "role": "target",
                        "agent": entry["harness"],
                        "snapshot_id": aggregate["snapshot_id"],
                        "config_hash": _digest(_config_record(cfgs[0]["config"])),
                        "input": {
                            "rollout_ordinal": ordinal,
                            "position": position,
                            "task": trajectory["task"],
                        },
                    }
                )
                if (entry["harness"], key) in target_keys:
                    index[(entry["harness"], key)].append(
                        {
                            "stage": label,
                            "rollout_ordinal": ordinal,
                            "position": position,
                            "aggregate_path": entry["path"],
                            "task_id": trajectory["task"]["task_id"],
                            "snapshot_id": aggregate["snapshot_id"],
                        }
                    )
            ordinal += 1
    return index


def summarize(records, predicate=lambda r: True):
    selected = [r for r in records if predicate(r)]
    return {
        "records": len(selected),
        "statuses": dict(
            Counter(r.get("trajectory_status", "unreadable") for r in selected)
        ),
        "model_status": dict(
            Counter(r.get("model", {}).get("status", "unverified") for r in selected)
        ),
        "activation_status": dict(
            Counter(
                r.get("activation", {}).get("status", "not_applicable")
                for r in selected
            )
        ),
        "exception_records": sum(bool(r["reasons"]) for r in selected),
    }


def main():
    out, manifest = freeze_manifest()
    entries = manifest["files"]
    print(
        json.dumps(
            {
                "prefix_manifest": str(out / "manifest.json"),
                "cutoff_utc": manifest["cutoff_utc"],
                "file_counts": dict(
                    Counter((e["harness"] + "/" + e["group"]) for e in entries)
                ),
            }
        ),
        flush=True,
    )
    initial = {}
    for e in entries:
        if e["group"] == "plan":
            initial[e["harness"]] = stable_json(e)[0]["initial_snapshot"]
    snapshot_sources = defaultdict(list)
    snapshot_entries = defaultdict(list)
    for e in entries:
        if e["group"] == "snapshots":
            key = (e["harness"], Path(e["path"]).stem)
            snapshot_sources[key].append(e["path"])
            snapshot_entries[key].append(e)
    info_index = {}
    snapshot_issues = []
    for key, candidates in snapshot_entries.items():
        for e in candidates:
            try:
                stable_bytes(e)
                snapshot = Snapshot.load(ROOT / e["path"])
                stable_bytes(e)
                if snapshot.id != key[1]:
                    raise ValueError("snapshot_filename_id_mismatch")
                info_index[key] = snapshot_info(key[0], snapshot)
                break
            except Exception as error:
                snapshot_issues.append(
                    {
                        "path": e["path"],
                        "reason": type(error).__name__ + ":" + str(error)[:150],
                    }
                )
    target_keys = {
        (e["harness"], Path(e["path"]).stem) for e in entries if e["group"] == "target"
    }
    stage_issues = []
    stages = stage_index(entries, target_keys, stage_issues)
    print(
        json.dumps(
            {
                "prefix_stage_indexed_targets": len(stages),
                "snapshots": len(info_index),
                "stage_issues": len(stage_issues),
            }
        ),
        flush=True,
    )
    records = []
    for e in entries:
        if e["group"] not in ("target", "worker"):
            continue
        row = {
            "cache_path": e["path"],
            "harness": e["harness"],
            "role": e["group"],
            "reasons": [],
        }
        try:
            record, checksum = stable_json(e)
            trajectory = record["trajectory"]
            sid = record.get("snapshot_id")
            row.update(
                cache_sha256=checksum,
                task_id=(trajectory.get("task") or {}).get("task_id"),
                snapshot_id=sid,
                trajectory_status=trajectory.get("status"),
                initial_class=(
                    "initial" if sid == initial[e["harness"]] else "noninitial"
                )
                if e["group"] == "target"
                else "not_applicable",
            )
            for ok, reason in [
                (record.get("version") == 2, "cache_version_mismatch"),
                (
                    record.get("key") == Path(e["path"]).stem,
                    "cache_key_filename_mismatch",
                ),
                (
                    trajectory.get("status") == "finished",
                    "nonfinished_in_completed_cache",
                ),
            ]:
                if not ok:
                    row["reasons"].append(reason)
            cfgs = configs(trajectory.get("messages", []))
            if not cfgs:
                row["reasons"].append("RunConfig:missing")
            for cfg in cfgs:
                if cfg.get("snapshot_id") != sid:
                    row["reasons"].append("RunConfig_snapshot_id_mismatch")
                if _digest(_config_record(cfg["config"])) != record["config_hash"]:
                    row["reasons"].append("RunConfig_config_hash_mismatch")
            row["model"] = model_audit(e["harness"], e["group"], trajectory)
            row["reasons"].extend(
                "model:" + reason for reason in row["model"]["reasons"]
            )
            if e["group"] == "target":
                key = (e["harness"], record["key"])
                associations = stages.get(key, [])
                identities = {
                    (
                        s["stage"],
                        s["rollout_ordinal"],
                        s["position"],
                        s["task_id"],
                        s["snapshot_id"],
                    )
                    for s in associations
                }
                row["stage_associations"] = associations
                row["stage_status"] = (
                    "reliable"
                    if len(identities) == 1
                    else "unassigned"
                    if not identities
                    else "conflict"
                )
                row["stage"] = (
                    next(iter(identities))[0]
                    if len(identities) == 1
                    else row["stage_status"]
                )
                if len(identities) > 1:
                    row["reasons"].append("conflicting_stage_associations")
                if any(
                    s["task_id"] != row["task_id"] or s["snapshot_id"] != sid
                    for s in associations
                ):
                    row["reasons"].append("stage_identity_mismatch")
                if e["harness"] == "claude_code":
                    inputs = [
                        m for m in trajectory["messages"] if m.get("type") == "RunInput"
                    ]
                    if not inputs or any(m.get("snapshot_id") != sid for m in inputs):
                        row["reasons"].append(
                            "RunInput_snapshot_id_mismatch_or_missing"
                        )
                row["activation"] = activation_audit(
                    e["harness"], record, info_index.get((e["harness"], sid))
                )
                row["reasons"].extend(
                    "activation:" + reason for reason in row["activation"]["reasons"]
                )
        except Exception as error:
            row["reasons"].append(
                "audit_read_or_schema_error:"
                + type(error).__name__
                + ":"
                + str(error)[:150]
            )
        row["reasons"] = sorted(set(row["reasons"]))
        records.append(row)
    public_snapshots = [
        {
            "harness": key[0],
            "source_paths": snapshot_sources[key],
            **{k: v for k, v in info.items() if not k.startswith("_")},
        }
        for key, info in sorted(info_index.items())
    ]
    exceptions = [r for r in records if r["reasons"]]
    summary = {
        "audit_kind": "prefix",
        "cutoff_utc": manifest["cutoff_utc"],
        "manifest_path": str(out / "manifest.json"),
        "script_sha256": sha(Path(__file__).read_bytes()),
        "limitations": [
            "Fixed completed-cache prefix only; not a final experiment certification.",
            "MiniAgent usage.model_calls.model records requested model selection; provider response model is not retained.",
            "Claude SDK init and usage model labels are separate from AssistantMessage response-reported labels.",
            "Gateway response labels do not independently establish underlying model weights.",
            "Exact skill context inclusion/activation is verified, not semantic adherence.",
            "Stage is reliable only when the full cache digest reconstructs from a captured scored aggregate; unfinished rollouts can be unassigned.",
            "Auxiliary error artifacts are counted separately and excluded from completed-cache denominators; their content is not audited.",
            "Initial scaffold skill receives the same activation checks as evolved skills; missing activation is never waived.",
        ],
        "harnesses": {},
        "snapshot_issues": snapshot_issues,
        "stage_index_issues": stage_issues,
        "exception_records": len(exceptions),
    }
    for harness in HARNESSES:
        target = [
            r for r in records if r["harness"] == harness and r["role"] == "target"
        ]
        worker = [
            r for r in records if r["harness"] == harness and r["role"] == "worker"
        ]
        hs = {
            "initial_snapshot": initial[harness],
            "target": summarize(target),
            "worker": summarize(worker),
            "target_by_initial_class": {
                c: summarize(target, lambda r, c=c: r.get("initial_class") == c)
                for c in ("initial", "noninitial")
            },
            "target_by_stage": {
                c: summarize(target, lambda r, c=c: r.get("stage") == c)
                for c in sorted({r.get("stage", "unverified") for r in target})
            },
            "target_stage_status": dict(
                Counter(r.get("stage_status", "unverified") for r in target)
            ),
            "target_by_snapshot": {
                sid: summarize(target, lambda r, sid=sid: r.get("snapshot_id") == sid)
                for sid in sorted({r.get("snapshot_id") for r in target}, key=str)
            },
            "auxiliary_error_artifact_count": sum(
                e["harness"] == harness and e["group"] == "auxiliary_error_artifacts"
                for e in entries
            ),
        }
        summary["harnesses"][harness] = hs
    dump(out / "summary.json", summary)
    dump(out / "exceptions.json", exceptions)
    dump(out / "snapshot-skill-metadata.json", public_snapshots)
    with (out / "records.jsonl").open("w") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "prefix_output_dir": str(out),
                "exception_records": len(exceptions),
                "summary": {
                    h: {k: v for k, v in data.items() if k != "target_by_snapshot"}
                    for h, data in summary["harnesses"].items()
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
