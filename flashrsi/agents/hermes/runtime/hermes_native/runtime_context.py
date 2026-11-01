"""Explicit Snapshot and task facts rendered with upstream prompt wording."""

from __future__ import annotations

import platform
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def runtime_context(snapshot_root, cwd, settings, *, now=None):
    timezone = settings.get("timezone")
    try:
        zone = ZoneInfo(timezone) if timezone else None
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        zone = None
    now = now or (datetime.now(zone) if zone else datetime.now().astimezone())
    started = settings.get("_runtime_started_at")
    start = datetime.fromisoformat(started) if started else now
    if start.tzinfo is None:
        start = start.astimezone()
    start = start.astimezone(now.tzinfo)
    iana = getattr(now.tzinfo, "key", None)
    abbreviation, offset = now.strftime("%Z"), now.strftime("%z")
    bits = [iana] if iana else []
    if abbreviation and abbreviation != iana:
        bits.append(abbreviation)
    if offset:
        bits.append(f"UTC{offset[:3]}:{offset[3:]}")
    suffix = f" ({', '.join(bits)})" if bits else ""
    stamp = f"Conversation started: {start:%A, %B %d, %Y}{suffix}"
    if now.strftime("%Y%m%d") != start.strftime("%Y%m%d"):
        stamp += f"\nToday's date (as of the last context rebuild): {now:%A, %B %d, %Y} — trust this over the start date for what day it is now; query tools for exact time."
    llm = settings.get("llm", {})
    for label, value in (
        (
            "Session ID",
            settings.get("session_id") if settings.get("pass_session_id") else None,
        ),
        ("Model", llm.get("model_name")),
        ("Provider", llm.get("provider")),
        ("Platform", settings.get("platform")),
    ):
        if value:
            stamp += f"\n{label}: {value}"
    root = Path(snapshot_root)
    profile = settings.get("profile_name", "default")
    if profile == "default":
        profile_line = (
            f"Active Hermes profile: default. Other profiles (if any) live under {root}/profiles/<name>/. Each profile has its own "
            "skills/, plugins/, cron/, and memories/ that affect a different session than this one. Do not modify another profile's "
            "skills/plugins/cron/memories unless the user explicitly directs you to."
        )
    else:
        default_root = settings.get("profile_root", root)
        profile_line = (
            f"Active Hermes profile: {profile}. This session reads and writes {root}/. The default profile's data lives at "
            f"{default_root}/skills/, {default_root}/plugins/, {default_root}/cron/, {default_root}/memories/ — those belong to a different session run from a different shell. "
            "Do NOT modify another profile's skills/plugins/cron/memories unless the user explicitly directs you to."
        )
    host = settings.get("_runtime_host") or (
        f"macOS ({platform.mac_ver()[0] or platform.release()})"
        if sys.platform == "darwin"
        else f"{platform.system()} ({platform.release()})"
    )
    environment = f"Host: {host}\nUser home directory: {settings.get('user_home') or Path.home()}\nCurrent working directory: {cwd}"
    scratch = settings.get("_scratch_dir") or settings.get("scratch_dir")
    if scratch:
        environment += f"\nScratch directory: {scratch} (TMPDIR points here; write temporary files and probes there, never under the system temp dir)"
    hint = (settings.get("agent") or {}).get("environment_hint", "")
    if hint and str(hint).strip():
        environment += "\n\n" + str(hint).strip()
    return profile_line, stamp, environment
