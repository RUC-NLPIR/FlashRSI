"""Pinned HF experiment profiles, also readable by the YAML-only launcher."""

from collections.abc import Mapping

REPO = "RUC-NLPIR/FlashRSI"
REVISION = "8e226b748e648d4e001cf247f255cfb9eb752292"
LEGACY_REVISIONS = {
    "1b976eec446eec4cb5354c07bc81b27f92b69c49",
    "f950bd8dc40a9b498d9b1edbf5ca71720a38cd3d",
}
PROFILES = {
    name: (name, {})
    for name in (
        "aime",
        "alfworld",
        "appworld",
        "bbeh",
        "bfcl",
        "browsecomp",
        "deepsearchqa",
        "deepswe",
        "harvey_lab",
        "hotpotqa",
        "math",
        "musique",
        "nq",
        "officeqa_pro",
        "searchqa",
        "supergpqa",
        "swe_bench",
        "tau3_banking",
        "travelplanner",
        "triviaqa",
        "twowiki_multihopqa",
        "widesearch",
        "workbench",
    )
}
PROFILES.update(
    {
        "terminal_bench_2_0": ("terminal_bench", {"version": "2.0"}),
        "spreadsheetbench2": ("spreadsheetbench2", {"category": "all"}),
        "swe_bench_pro": ("swe_bench_pro", {"subset": "all"}),
        **{
            f"tau2_{d}": ("tau2", {"domain": d, "task_split": "base"})
            for d in ("airline", "retail", "telecom")
        },
        **{f"jobbench_{c}": ("jobbench", {"collection": c}) for c in ("main", "easy")},
        **{
            f"livemathbench_{v}_{lang}": (
                "livemathbench",
                {
                    "version": v,
                    "dataset_languages": [lang],
                    "dataset_splits": ["CNMO", "CCEE", "AMC", "WLPMC"]
                    if v == "202412"
                    else ["all"],
                },
            )
            for v, lang in (("202412", "cn"), ("202412", "en"), ("202505", "en"))
        },
    }
)
ALIASES = {name + "_experiment_v1": name for name in PROFILES}
ALIASES.update(
    {
        "aime_2025_2026_experiment_v1": "aime",
        "terminal_bench_experiment_v1": "terminal_bench_2_0",
    }
)
BENCHMARKS = tuple(sorted({benchmark for benchmark, _ in PROFILES.values()}))


def selected(config):
    source = config.get("dataset", {})
    return (
        isinstance(source, Mapping)
        and source.get("source") == REPO
        and isinstance(source.get("config"), str)
        and (source.get("config") in PROFILES or source.get("config") in ALIASES)
    )
