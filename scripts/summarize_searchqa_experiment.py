"""Read saved experiment evidence without making model calls or changing a run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flashrsi._run_summary import _write_run_summary  # noqa: E402

PAPER_REFERENCE = {
    "model": "GPT-5.5",
    "source": "https://arxiv.org/html/2605.23904v1#S3.T1",
    "rows": [
        {"harness": "direct", "baseline": 77.7, "skillopt": 87.3},
        {"harness": "codex", "baseline": 81.8, "skillopt": 87.3},
        {"harness": "claude_code", "baseline": 81.9, "skillopt": 85.9},
    ],
}


def _read(path):
    return json.loads(path.read_text()) if path.exists() else None


def _alive(pid):
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def _usage(usage):
    """Normalize only the canonical usage, never duplicate message-level usage.

    OpenAI prompt_tokens already includes cached tokens. Anthropic's modelUsage
    reports uncached input separately from cache reads/writes; sum those once.
    Gateway prices are unknown, so SDK cost estimates are deliberately omitted.
    """
    if "model_calls" in usage:
        result = {"input_tokens": 0, "output_tokens": 0}
        for call in usage["model_calls"]:
            counts = _usage(call.get("usage", {}))
            for key in result:
                result[key] += counts[key]
        return result
    if usage.get("model_usage"):
        return {
            "input_tokens": sum(
                row.get("inputTokens", 0)
                + row.get("cacheReadInputTokens", 0)
                + row.get("cacheCreationInputTokens", 0)
                for row in usage["model_usage"].values()
            ),
            "output_tokens": sum(
                row.get("outputTokens", 0) for row in usage["model_usage"].values()
            ),
        }
    return {
        "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0,
        "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0))
        or 0,
    }


def _cache_usage(experiment):
    totals = {}
    for role in ("target", "worker"):
        values = {"finished_requests": 0, "input_tokens": 0, "output_tokens": 0}
        for path in (experiment / "cache" / role).glob("*/*.json"):
            record = _read(path)
            trajectory = record["trajectory"]
            values["finished_requests"] += int(trajectory["status"] == "finished")
            for key, number in _usage(trajectory.get("usage", {})).items():
                values[key] += number
        values["failed_attempt_records"] = len(
            list((experiment / "cache/errors" / role).glob("*/*.json"))
        )
        totals[role] = values
    retry_paths = list((experiment / "cache/protocol_retries").glob("*/*/*.json"))
    if retry_paths:
        values = {
            "finished_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "failed_attempt_records": 0,
        }
        for path in retry_paths:
            trajectory = _read(path)["trajectory"]
            finished = trajectory["status"] == "finished"
            values["finished_requests"] += int(finished)
            values["failed_attempt_records"] += int(not finished)
            for key, number in _usage(trajectory.get("usage", {})).items():
                values[key] += number
        totals["worker_protocol_retry"] = values
    return totals


def collect(experiment):
    plan = _read(experiment / "plan.json")
    if plan is None:
        return {"harness": experiment.name, "status": "pending"}
    result = _read(experiment / "result.json")
    state = _read(experiment / "status.json") or {"status": "prepared"}
    attempt = state.get("attempt") or (result or {}).get("attempt")
    if attempt:
        attempt = str(experiment / "attempts" / Path(attempt).name)
    report = {
        "harness": experiment.name,
        "status": state["status"],
        "process_live_at_inspection": _alive(state.get("pid")),
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "profile": plan["profile"],
        "split_counts": plan["split_counts"],
        "worker_model": plan["config"]["agent"]["llm"]["model_name"],
        "evolver_model": plan["config"]["algorithm"]["worker"]["llm"]["model_name"],
        "attempt": attempt,
        "error": state.get("error"),
        "calls": _cache_usage(experiment),
        "dev_curve": [],
    }
    if attempt:
        for path in sorted((Path(attempt) / "trajectories").glob("*.json")):
            if path.name.endswith("-baseline.json"):
                rows = _read(path)["trajectories"]
                baseline = sum(row["metrics"]["hard"] for row in rows) / len(rows)
                report["initial_dev_hard"] = baseline
                report["dev_curve"].append({"kind": "initial", "best": baseline})
            elif path.name.endswith("-decision.json"):
                decision = _read(path)
                point = {
                    key: decision.get(key)
                    for key in (
                        "epoch",
                        "step",
                        "kind",
                        "score",
                        "baseline_score",
                        "accepted",
                        "reason",
                    )
                }
                point["best"] = (
                    decision["score"]
                    if decision.get("accepted")
                    else decision.get("baseline_score", report["dev_curve"][-1]["best"])
                )
                report["dev_curve"].append(point)
    report["accepted_candidates"] = sum(
        bool(point.get("accepted")) for point in report["dev_curve"]
    )
    if result is not None:
        count = plan["split_counts"]["test"]
        if result["status"] != "finished" or any(
            result[field]["tasks"] != count or result[field]["finished"] != count
            for field in ("baseline_test", "evolved_test")
        ):
            raise ValueError(
                f"Incomplete test evidence in {experiment / 'result.json'}"
            )
        for key in (
            "baseline_test",
            "evolved_test",
            "paired_comparison",
            "final_snapshot",
        ):
            report[key] = result[key]
        report["initial_snapshot"] = result["initial_snapshot"]
        report["skill_changed"] = result["final_snapshot"] != result["initial_snapshot"]
        report["test_used_for_selection"] = result["test_used_for_selection"]
        report["status"] = "finished"
    return report


def render(report):
    lines = [
        "# SkillOpt / SearchQA 实验结果",
        "",
        f"记录时间：{report['inspected_at']}。Profile：`{report['profile']}`。",
        "",
        "答题模型 DeepSeek-v4-flash，演化模型 DeepSeek-v4-pro。",
        "此处为迁移复现，模型与部分 harness、算法细节和论文不同。",
        "",
        "| Harness | 状态 | 初始 dev EM | 初始 test EM | 最终 test EM | test F1（前→后） | 提升百分点 | 技能改变 |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for row in report["experiments"]:
        before = row.get("baseline_test", {})
        after = row.get("evolved_test", {})
        fmt = lambda value: "—" if value is None else f"{value * 100:.2f}%"  # noqa: E731
        delta = row.get("paired_comparison", {}).get("delta_percentage_points")
        lines.append(
            f"| {row['harness']} | {row['status']} | {fmt(row.get('initial_dev_hard'))} "
            f"| {fmt(before.get('hard'))} | {fmt(after.get('hard'))} "
            f"| {fmt(before.get('f1'))} → {fmt(after.get('f1'))} "
            f"| {'—' if delta is None else f'{delta:+.2f}'} "
            f"| {row.get('skill_changed', '—')} |"
        )
    lines.extend(
        [
            "",
            "若技能未改变，前后差异来自独立模型采样，不能归因于演化。",
            "smoke/pilot 的小样本成绩不能当作论文级全量结果。",
            "",
        ]
    )
    for row in report["experiments"]:
        lines.extend([f"## {row['harness']}", ""])
        if row["status"] == "pending":
            lines.extend(["等待执行。", ""])
            continue
        lines.append(
            f"划分：`{row['split_counts']}`；接受候选数：{row['accepted_candidates']}。"
        )
        if row.get("paired_comparison"):
            pair = row["paired_comparison"]
            lines.append(
                f"改善 {pair['improved_tasks']} 题，退步 {pair['regressed_tasks']} 题；"
                f"配对 bootstrap 95% 区间：{pair['paired_bootstrap_95pct_pp']} 个百分点。"
            )
        if row.get("error"):
            lines.append(f"运行错误：`{row['error']}`")
        lines.extend(
            [
                "",
                "| 调用角色 | 成功请求 | 输入 tokens（含缓存） | 输出 tokens | 失败尝试记录 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for role, counts in row["calls"].items():
            lines.append(
                f"| {role} | {counts['finished_requests']} | {counts['input_tokens']} "
                f"| {counts['output_tokens']} | {counts['failed_attempt_records']} |"
            )
        lines.extend(
            [
                "",
                "上表为成功缓存请求口径，未计失败用量。完整成功／失败用量与 SDK 费用见下方实验结束汇总；SDK 估价不作为网关账单。",
                "",
            ]
        )
    lines.extend(
        [
            "## 实验结束汇总",
            "",
            "- [MiniAgent 用量与费用](miniagent/end-summary.md)",
            "- [Claude Code 用量与费用](claude_code/end-summary.md)",
            "",
        ]
    )
    lines.extend(
        [
            "## 论文参考（GPT-5.5）",
            "",
            "| Harness | 初始 EM | SkillOpt EM |",
            "| --- | ---: | ---: |",
        ]
    )
    for row in PAPER_REFERENCE["rows"]:
        lines.append(f"| {row['harness']} | {row['baseline']}% | {row['skillopt']}% |")
    lines.extend(
        [
            "",
            f"[论文 Table 1]({PAPER_REFERENCE['source']})。模型不同，不是同一实验条件。",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=ROOT / "runs/skillopt-searchqa-deepseek"
    )
    parser.add_argument("--profile", choices=("smoke", "pilot", "full"), default="full")
    args = parser.parse_args()
    destination = args.run_root.resolve() / args.profile
    report = {
        "profile": args.profile,
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "experiments": [
            collect(destination / name) for name in ("miniagent", "claude_code")
        ],
        "paper_reference": PAPER_REFERENCE,
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("miniagent", "claude_code"):
        experiment = destination / name
        if experiment.exists():
            _write_run_summary(experiment, emit=False)
    for name, content in (
        ("report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
        ("report.md", render(report)),
    ):
        temporary = destination / (name + ".tmp")
        temporary.write_text(content)
        temporary.replace(destination / name)
    print(destination / "report.md")


if __name__ == "__main__":
    main()
