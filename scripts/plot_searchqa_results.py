"""Plot a saved SearchQA report without touching the experiment environment.

Run from the repository root in an isolated uv environment:
  uv run --no-project --python 3.13 --with matplotlib==3.10.7 python \
    scripts/plot_searchqa_results.py \
    --report runs/skillopt-searchqa-deepseek/full/report.json

All figures and plot metadata are written under full/figures. Report content is
read once, and its SHA-256 names the outputs so different prefixes stay distinct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "runs/skillopt-searchqa-deepseek/full/figures"
HARNESSES = ("miniagent", "claude_code")
LABELS = {"miniagent": "MiniAgent", "claude_code": "Claude Code"}
COLORS = {"miniagent": "#2563EB", "claude_code": "#C66A12"}


def score(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a numeric score, not {value!r}")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{label} must be finite and in [0, 1]")
    return float(value)


def experiment_rows(report):
    rows = report.get("experiments", [])
    result = {}
    for harness in HARNESSES:
        matches = [row for row in rows if row.get("harness") == harness]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {harness} experiment")
        result[harness] = matches[0]
    return result


def development_points(row):
    """Keep record order, including slow updates at the final step of their epoch."""
    if row.get("split_counts", {}).get("dev") != 200:
        raise ValueError(f"{row['harness']}: development chart requires 200 questions")
    curve = row.get("dev_curve", [])
    if not curve or curve[0].get("kind") != "initial":
        raise ValueError(f"{row['harness']}: initial development point is missing")
    epoch_ends = {}
    for point in curve:
        if point.get("kind") == "fast":
            step, epoch = point.get("step"), point.get("epoch")
            if type(step) is not int or step < 1 or type(epoch) is not int or epoch < 0:
                raise ValueError("Fast development point needs integer step and epoch")
            epoch_ends[epoch] = max(epoch_ends.get(epoch, 0), step)
    current = score(curve[0].get("best"), "initial development EM")
    points = [
        {
            "step": 0,
            "kind": "initial",
            "best": current,
            "candidate": None,
            "accepted": False,
            "reason": None,
        }
    ]
    for point in curve[1:]:
        kind = point.get("kind")
        if kind == "fast":
            step = point["step"]
        elif kind in ("slow", "meta"):
            if point.get("epoch") not in epoch_ends:
                raise ValueError(
                    f"Cannot locate the end of epoch {point.get('epoch')} for {kind}"
                )
            step = epoch_ends[point["epoch"]]
        else:
            raise ValueError(f"Unknown development update kind: {kind}")
        if step < points[-1]["step"]:
            raise ValueError("Development points are not in chronological step order")
        raw = point.get("score")
        candidate = None if raw is None else score(raw, "candidate development EM")
        accepted = point.get("accepted") is True
        if point.get("reason") == "invalid_patch" and candidate is not None:
            raise ValueError("An invalid patch must not have an evaluated score")
        if accepted and candidate is None:
            raise ValueError("An accepted candidate must have an evaluated score")
        if accepted:
            if candidate < current:
                raise ValueError(
                    "Accepted candidate decreases selected development score"
                )
            current = candidate
        # Some rejected edits have no baseline/best field; preserve selected best.
        reported_best = point.get("best")
        if reported_best is not None and not math.isclose(
            score(reported_best, "reported selected best"), current, abs_tol=1e-12
        ):
            raise ValueError("Reported best disagrees with accepted-candidate history")
        points.append(
            {
                "step": step,
                "epoch": point.get("epoch"),
                "kind": kind,
                "best": current,
                "candidate": candidate,
                "accepted": accepted,
                "reason": point.get("reason"),
            }
        )
    return points


def test_readiness(report, rows):
    """Gate on the full report's completed test counts; never substitute dev data."""
    reasons = []
    if report.get("profile") != "full":
        reasons.append("report profile is not full")
    for harness, row in rows.items():
        if row.get("profile") != "full":
            reasons.append(f"{harness}: profile is not full")
        if row.get("status") != "finished":
            reasons.append(f"{harness}: status is {row.get('status')!r}, not finished")
        if row.get("split_counts", {}).get("test") != 1400:
            reasons.append(f"{harness}: configured test size is not 1400")
        if row.get("test_used_for_selection") is not False:
            reasons.append(
                f"{harness}: held-out test selection flag is not verified false"
            )
        for name in ("baseline_test", "evolved_test"):
            block = row.get(name)
            if not isinstance(block, dict):
                reasons.append(f"{harness}: {name} is absent")
                continue
            if any(
                type(block.get(k)) is not int or block[k] != 1400
                for k in ("tasks", "finished")
            ):
                reasons.append(
                    f"{harness}: {name} does not contain 1400/1400 finished tasks"
                )
            try:
                score(block.get("hard"), f"{harness}.{name}.hard")
            except ValueError as error:
                reasons.append(str(error))
    return reasons


def model_caption(rows):
    workers = sorted({row.get("worker_model", "unrecorded") for row in rows.values()})
    evolvers = sorted({row.get("evolver_model", "unrecorded") for row in rows.values()})
    return f"Answering: {', '.join(workers)}   |   Evolver: {', '.join(evolvers)}"


def save_figure(fig, stem, dpi):
    paths = []
    for suffix in ("png", "svg"):
        path = FIGURES / f"{stem}.{suffix}"
        fig.savefig(
            path,
            dpi=dpi,
            facecolor="white",
            metadata={"Creator": "SearchQA result plotter"},
        )
        paths.append(str(path))
    return paths


def plot_development(plt, rows, points, report, tag, dpi):
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator, PercentFormatter

    fig = plt.figure(figsize=(12, 7.8))
    grid = fig.add_gridspec(
        2,
        1,
        height_ratios=(6, 1),
        hspace=0.12,
        left=0.105,
        right=0.94,
        bottom=0.235,
        top=0.77,
    )
    ax = fig.add_subplot(grid[0])
    events = fig.add_subplot(grid[1], sharex=ax)
    complete = all(row.get("status") == "finished" for row in rows.values())
    state = "Completed runs" if complete else "Running prefix"
    fig.suptitle(
        "SkillOpt on SearchQA — Development",
        x=0.105,
        ha="left",
        y=0.967,
        fontsize=21,
        fontweight="semibold",
    )
    fig.text(
        0.105,
        0.916,
        f"200 development questions  ·  Official normalized EM  ·  {state}",
        fontsize=11.5,
        color="#475569",
    )
    fig.text(0.105, 0.876, model_caption(rows), fontsize=10, color="#64748B")
    values = []
    xmax = max(point["step"] for ps in points.values() for point in ps)
    has_slow = False
    for lane, harness in enumerate(HARNESSES):
        ps, color = points[harness], COLORS[harness]
        x, y = [p["step"] for p in ps], [p["best"] for p in ps]
        values.extend(y)
        ax.step(x, y, where="post", color=color, lw=2.5, zorder=3)
        ax.scatter([0], [y[0]], s=48, color=color, edgecolor="white", zorder=5)
        for point in ps[1:]:
            if point["candidate"] is None:
                marker = "x" if point["reason"] == "invalid_patch" else "+"
                events.scatter(
                    point["step"],
                    lane,
                    color=color,
                    marker=marker,
                    s=62,
                    linewidths=1.8,
                    zorder=4,
                )
                continue
            values.append(point["candidate"])
            slow = point["kind"] == "slow"
            has_slow |= slow
            ax.scatter(
                point["step"],
                point["candidate"],
                marker="D" if slow else "o",
                s=66 if slow else 42,
                linewidths=1.3,
                facecolors=color if point["accepted"] else "white",
                edgecolors=color,
                zorder=5,
            )
        ax.annotate(
            f"{y[-1] * 100:.1f}%",
            xy=(x[-1], y[-1]),
            xytext=(9, 10 if lane == 0 else -17),
            textcoords="offset points",
            color=color,
            fontsize=11.5,
            fontweight="bold",
        )
    legend = [
        Line2D([0], [0], color=COLORS[h], lw=2.5, label=f"{LABELS[h]} selected best")
        for h in HARNESSES
    ]
    legend.append(
        Line2D(
            [0],
            [0],
            color="#475569",
            marker="o",
            linestyle="none",
            markerfacecolor="white",
            markersize=6,
            label="Fast candidate",
        )
    )
    if has_slow:
        legend.append(
            Line2D(
                [0],
                [0],
                color="#475569",
                marker="D",
                linestyle="none",
                markerfacecolor="white",
                markersize=6,
                label="Slow candidate",
            )
        )
    ax.legend(
        handles=legend,
        loc="lower left",
        bbox_to_anchor=(-0.005, 1.03),
        ncol=len(legend),
        frameon=False,
        handlelength=2,
        columnspacing=1.8,
        fontsize=10,
    )
    ax.set_ylabel("Development EM", fontsize=11)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10]))
    ax.set_ylim(max(0, min(values) - 0.035), min(1.02, max(values) + 0.035))
    ax.set_xlim(-0.4, xmax + max(1.5, xmax * 0.07))
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.tick_params(axis="x", labelbottom=False, length=0)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    events.set_yticks([0, 1], [LABELS[h] for h in HARNESSES], fontsize=9)
    events.set_ylim(1.7, -0.7)
    events.set_xlabel(
        "Completed fast-update step (initial = 0)", labelpad=10, fontsize=11
    )
    events.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=10))
    events.tick_params(axis="y", length=0, pad=8)
    for label, harness in zip(events.get_yticklabels(), HARNESSES):
        label.set_color(COLORS[harness])
    for lane in (0, 1):
        events.axhline(lane, color="#EEF2F6", linewidth=1, zorder=1)
    for side in ("top", "right", "left"):
        events.spines[side].set_visible(False)
    events.spines["bottom"].set_color("#CBD5E1")
    fig.text(
        0.105,
        0.115,
        "Filled candidates: accepted. Hollow candidates: evaluated, not accepted.",
        fontsize=9.5,
        color="#475569",
    )
    fig.text(
        0.105,
        0.087,
        "Event lanes: × invalid patch, + other unscored edit; neither is plotted as a zero score. Slow updates use their epoch’s final fast step.",
        fontsize=9,
        color="#64748B",
    )
    fig.text(
        0.105,
        0.043,
        f"Report inspected: {report.get('inspected_at', 'unrecorded')}   |   Development scores are separate from held-out test results.",
        fontsize=8.5,
        color="#64748B",
    )
    paths = save_figure(fig, f"searchqa_development_{tag}", dpi)
    plt.close(fig)
    return paths


def plot_test(plt, rows, report, tag, dpi):
    from matplotlib.patches import Patch
    from matplotlib.ticker import PercentFormatter

    fig, ax = plt.subplots(figsize=(9.5, 6.5))
    fig.subplots_adjust(left=0.105, right=0.94, bottom=0.22, top=0.73)
    fig.suptitle(
        "SkillOpt on SearchQA — Held-out test",
        x=0.105,
        ha="left",
        y=0.96,
        fontsize=20,
        fontweight="semibold",
    )
    fig.text(
        0.105,
        0.901,
        "1,400 questions per harness per condition  ·  All 5,600 answer records finished",
        fontsize=10.5,
        color="#475569",
    )
    fig.text(0.105, 0.855, model_caption(rows), fontsize=9.5, color="#64748B")
    for index, harness in enumerate(HARNESSES):
        row, color = rows[harness], COLORS[harness]
        before = score(row["baseline_test"]["hard"], "initial test EM")
        after = score(row["evolved_test"]["hard"], "evolved test EM")
        for x, value, alpha in [
            (index - 0.19, before, 0.3),
            (index + 0.19, after, 1.0),
        ]:
            ax.bar(x, value, width=0.32, color=color, alpha=alpha, zorder=3)
            ax.text(
                x,
                value + 0.018,
                f"{value * 100:.2f}%",
                ha="center",
                va="bottom",
                fontsize=11,
            )
        ax.text(
            index,
            -0.145,
            f"Δ {(after - before) * 100:+.2f} percentage points",
            transform=ax.get_xaxis_transform(),
            ha="center",
            fontsize=10,
            color=color,
        )
    ax.set_xticks(range(2), [LABELS[h] for h in HARNESSES], fontsize=11)
    ax.set_ylim(0, 1.07)
    ax.set_ylabel("Test EM (official normalized exact match)", fontsize=10)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(
        handles=[
            Patch(facecolor="#64748B", alpha=0.3, label="Initial skill"),
            Patch(facecolor="#64748B", label="Final selected skill"),
        ],
        loc="lower left",
        bbox_to_anchor=(-0.005, 1.02),
        frameon=False,
        ncol=2,
    )
    fig.text(
        0.105,
        0.069,
        "Test was not used for selection. Completion gate uses the saved report’s per-condition finished counts.",
        fontsize=8.5,
        color="#64748B",
    )
    fig.text(
        0.105,
        0.035,
        f"Report inspected: {report.get('inspected_at', 'unrecorded')}",
        fontsize=8.5,
        color="#64748B",
    )
    paths = save_figure(fig, f"searchqa_test_em_{tag}", dpi)
    plt.close(fig)
    return paths


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--report", type=Path, default=FIGURES.parent / "report.json")
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()
    if args.dpi < 72:
        parser.error("--dpi must be at least 72")
    raw = args.report.resolve().read_bytes()
    report = json.loads(raw)
    report_hash = hashlib.sha256(raw).hexdigest()
    tag = report_hash[:12]
    rows = experiment_rows(report)
    points = {h: development_points(row) for h, row in rows.items()}
    reasons = test_readiness(report, rows)
    FIGURES.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(FIGURES / ".matplotlib-cache")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "svg.fonttype": "none",
            "axes.labelcolor": "#334155",
            "xtick.color": "#475569",
            "ytick.color": "#475569",
            "font.size": 10,
        }
    )
    dev_paths = plot_development(plt, rows, points, report, tag, args.dpi)
    test_paths = [] if reasons else plot_test(plt, rows, report, tag, args.dpi)
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_report": str(args.report.resolve()),
        "source_report_sha256": report_hash,
        "source_inspected_at": report.get("inspected_at"),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_executable": sys.executable,
        "matplotlib_version": matplotlib.__version__,
        "development": {
            "split": "development",
            "questions": 200,
            "files": dev_paths,
            "plotted_points": points,
        },
        "test": {
            "generated": not reasons,
            "files": test_paths,
            "not_generated_reasons": reasons,
            "completion_evidence": "saved report counts, not a raw-trajectory certification",
        },
    }
    manifest = FIGURES / f"searchqa_plot_{tag}.json"
    manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "development_figures": dev_paths,
                "test_figures": test_paths,
                "test_not_generated_reasons": reasons,
                "plot_manifest": str(manifest),
                "python_executable": sys.executable,
                "matplotlib_version": matplotlib.__version__,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
