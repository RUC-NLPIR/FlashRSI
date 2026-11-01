"""Original Hermes skill discovery/catalog helpers; see UPSTREAM.md and LICENSE.

Only yaml_load is adapted to the already-required PyYAML safe loader.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from pathlib import Path, PurePath
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


def yaml_load(content: str):
    return yaml.safe_load(content)


PLATFORM_MAP = {"macos": "darwin", "linux": "linux", "windows": "win32"}

EXCLUDED_SKILL_DIRS = frozenset(
    (
        ".git",
        ".github",
        ".hub",
        ".archive",
        ".curator_backups",
        ".locks",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "__pycache__",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    )
)

SKILL_SUPPORT_DIRS = frozenset(("references", "templates", "assets", "scripts"))


def is_excluded_skill_path(path, *, root: Optional[Path] = None) -> bool:
    """True if *path* should be skipped by skill scanners (VCS/dependency/cache
    dirs + support packages). Apply to every SKILL.md from a direct ``rglob``."""
    parts = PurePath(str(path)).parts
    return any(part in EXCLUDED_SKILL_DIRS for part in parts) or is_skill_support_path(
        path, root=root
    )


def is_skill_support_path(path, *, root: Optional[Path] = None) -> bool:
    """True if *path* is under a support dir sitting directly inside a skill root
    (``skills/scripts/foo`` stays discoverable: no ``SKILL.md`` above ``scripts``)."""
    path_obj = path if isinstance(path, Path) else Path(str(path))
    parts = path_obj.parts
    base = root if root is not None and not path_obj.is_absolute() else Path()
    # Only components before the leaf can be containing support directories.
    return any(
        part in SKILL_SUPPORT_DIRS and (base / Path(*parts[:idx]) / "SKILL.md").exists()
        for idx, part in enumerate(parts[:-1])
        if idx > 0
    )


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown; returns (frontmatter_dict, body).
    Malformed YAML falls back to key:value line splitting. A leading UTF-8 BOM
    (Windows editors) is stripped first or it would defeat the ``---`` fence check."""
    content = content.removeprefix("\ufeff")
    end_match = (
        re.search(r"\n---\s*\n", content[3:]) if content.startswith("---") else None
    )
    if not end_match:
        return {}, content
    yaml_content = content[3 : end_match.start() + 3]
    body = content[end_match.end() + 3 :]
    frontmatter: dict[str, Any] = {}
    try:
        parsed = yaml_load(yaml_content)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except Exception:
        for line in yaml_content.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def skill_matches_platform_list(platforms: Any) -> bool:
    """Return True when *platforms* is compatible with the current OS."""
    if not platforms:
        return True
    if not isinstance(platforms, list):
        platforms = [platforms]
    current = sys.platform
    for platform in platforms:
        normalized = str(platform).lower().strip()
        mapped = PLATFORM_MAP.get(normalized, normalized)
        if current.startswith(mapped):
            return True
    return False


def skill_matches_platform(frontmatter: dict[str, Any]) -> bool:
    """True when the skill's ``platforms:`` list (absent = all) matches this OS."""
    return skill_matches_platform_list(frontmatter.get("platforms"))


_SHADOW_CHECKED: set[tuple[str, ...]] = set()


def provably_same_skill(skill_mds) -> bool:
    """True only when every path is the SAME skill: one resolved file (symlink view) or byte-identical
    content (copy). Anything else is two different skills sharing a name, and picking one by depth
    would let ``<root>/evil`` (``name: github``) shadow the real one."""
    try:
        if len({os.path.realpath(p) for p in skill_mds}) == 1:
            return True
        return (
            len({hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in skill_mds})
            == 1
        )
    except OSError:
        return False


def skill_candidate_rank(skill_md, root) -> tuple[bool, int]:
    """Same-root order of identical copies: a real SKILL.md beats a legacy flat ``<name>.md``,
    then the shallower path wins (shared by skill_view and :func:`resolve_skill_catalog`)."""
    skill_md = Path(skill_md)
    return (skill_md.name != "SKILL.md", len(skill_md.relative_to(root).parts))


def pick_skill_candidate(candidates) -> tuple[Optional[int], list[int]]:
    """Winner index among one identifier's ``(tier, root, rank, skill_md)`` candidates, plus the
    winning tier's contender indexes. The lowest tier wins; inside it a lone candidate wins, identical
    copies under one root resolve to the strictly best ``rank``, anything else is ambiguous (None)."""
    top = min(c[0] for c in candidates)
    contenders = [i for i, c in enumerate(candidates) if c[0] == top]
    if (
        len(contenders) > 1
        and len({candidates[i][1] for i in contenders}) == 1
        and provably_same_skill([candidates[i][3] for i in contenders])
    ):
        ranked = sorted(contenders, key=lambda i: candidates[i][2])
        if candidates[ranked[0]][2] != candidates[ranked[1]][2]:
            return ranked[0], contenders
    return (contenders[0] if len(contenders) == 1 else None), contenders


def is_disabled_entry(entry: dict[str, Any], disabled: set[str]) -> bool:
    """``skills.disabled`` matches a resolved catalog entry by its declared name OR its ``load_name`` —
    the exact path a same-tier duplicate's list/config/web row shows (``a/one``) and saves. A unique
    copy elsewhere that merely sits at the same relative path is not matched."""
    return not disabled.isdisjoint(
        {str(entry["name"]), entry.get("load_name")} - {None}
    )


def resolve_skill_catalog(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of scanned skills (each with ``name``, ``tier``, ``root`` and ``path`` = its SKILL.md)
    annotated with what skill_view() resolves, using its aliases (declared name, directory name, path
    relative to the root) and :func:`pick_skill_candidate`. Adds ``relative_path`` and ``status``:
    ``unique`` (``load_name`` = name), ``ambiguous`` (``load_name`` = the exact relative path, or None
    when even that is shared) or ``shadowed`` (a higher tier owns the name: hidden, warned once)."""
    out = [dict(e) for e in entries]
    owners: dict[str, list[int]] = {}
    for i, e in enumerate(out):
        skill_dir = Path(e["path"]).parent
        e["relative_path"] = skill_dir.relative_to(e["root"]).as_posix()
        for alias in {str(e["name"]), skill_dir.name, e["relative_path"]}:
            owners.setdefault(alias, []).append(i)
    winner: dict[str, Optional[int]] = {}
    for alias, idxs in owners.items():
        won, _ = pick_skill_candidate(
            [
                (
                    out[j]["tier"],
                    str(out[j]["root"]),
                    skill_candidate_rank(out[j]["path"], out[j]["root"]),
                    out[j]["path"],
                )
                for j in idxs
            ]
        )
        winner[alias] = None if won is None else idxs[won]
    for i, e in enumerate(out):
        name, rel = str(e["name"]), e["relative_path"]
        higher = [j for j in owners[name] if out[j]["tier"] < e["tier"]]
        if higher or winner[name] not in (
            None,
            i,
        ):  # lower tier, or an identical same-root copy
            e.update(status="shadowed", load_name=None)
            # A symlink view or byte-identical copy of the winner hides nothing worth a warning.
            key = (str(e["path"]), *sorted(str(out[j]["path"]) for j in higher))
            if higher and key not in _SHADOW_CHECKED:
                _SHADOW_CHECKED.add(key)
                if not any(
                    provably_same_skill([e["path"], out[j]["path"]]) for j in higher
                ):
                    logger.warning(
                        "Skill '%s' at %s is shadowed by a higher-precedence copy "
                        "(project > local > create_dir > external_dirs)",
                        name,
                        e["path"],
                    )
        elif winner[name] == i:
            e.update(status="unique", load_name=name)
        else:
            e.update(status="ambiguous", load_name=rel if winner[rel] == i else None)
    return out


def iter_skill_index_files(skills_dir: Path, filename: str):
    """Walk skills_dir yielding sorted paths matching *filename*; prunes
    EXCLUDED_SKILL_DIRS and support dirs of skill roots."""
    matches: list[str] = []
    for root, dirs, files in os.walk(str(skills_dir), followlinks=True):
        has_skill_md = "SKILL.md" in files
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDED_SKILL_DIRS
            and not (has_skill_md and d in SKILL_SUPPORT_DIRS)
        ]
        if filename in files:
            matches.append(os.path.join(root, filename))
    yield from map(Path, sorted(matches))


SKILL_PROMPT_DESC_LIMIT = 60


def _normalize_skill_description(frontmatter: dict[str, Any]) -> str:
    """Normalize a skill's description field for comparison/truncation."""
    raw_desc = frontmatter.get("description", "")
    return str(raw_desc).strip().strip("'\"") if raw_desc else ""


def extract_skill_description(frontmatter: dict[str, Any]) -> str:
    """Extract a system-prompt-length description from parsed frontmatter."""
    desc = _normalize_skill_description(frontmatter)
    return (
        desc[: SKILL_PROMPT_DESC_LIMIT - 3] + "..."
        if len(desc) > SKILL_PROMPT_DESC_LIMIT
        else desc
    )
