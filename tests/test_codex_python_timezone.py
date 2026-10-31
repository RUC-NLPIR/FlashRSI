"""Pinned Linux IANA lookup and the native paired UTC date/zone fallback."""

import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from flashrsi.agents.codex.python_core import context


def _linux_context(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.delenv("TZ", raising=False)
    real_path = Path

    def path(value):
        text = str(value)
        if text == "/etc" or text.startswith("/etc/"):
            return real_path(tmp_path) / text.removeprefix("/etc").lstrip("/")
        return real_path(value)

    monkeypatch.setattr(context, "Path", path)


def test_missing_linux_zone_falls_back_to_utc_date_and_etc_utc_together(
    tmp_path, monkeypatch
):
    _linux_context(monkeypatch, tmp_path)
    real_datetime = datetime.datetime

    class Clock:
        @classmethod
        def now(cls, tz=None):
            if tz is datetime.timezone.utc:
                return real_datetime(2026, 10, 29, 23, 30, tzinfo=tz)
            local = real_datetime(
                2026,
                10,
                30,
                13,
                30,
                tzinfo=datetime.timezone(datetime.timedelta(hours=14)),
            )
            return SimpleNamespace(astimezone=lambda: local)

    monkeypatch.setattr(
        context, "datetime", SimpleNamespace(datetime=Clock, timezone=datetime.timezone)
    )
    result = context.environment_context({}, tmp_path)
    assert "<current_date>2026-10-29</current_date>" in result
    assert "<timezone>Etc/UTC</timezone>" in result


@pytest.mark.parametrize(
    "target,expected",
    [
        ("/usr/share/zoneinfo/Etc/UTC", "Etc/UTC"),
        ("../usr/share/zoneinfo/Asia/Shanghai", "Asia/Shanghai"),
        ("/etc/zoneinfo/Europe/Paris", "Europe/Paris"),
        ("../etc/zoneinfo/Europe/London", "Europe/London"),
        ("/usr/share/zoneinfo/America/../Asia/Tokyo", "America/../Asia/Tokyo"),
    ],
)
def test_linux_zone_reads_raw_symlink_before_timezone_file_and_ignores_tz(
    tmp_path, monkeypatch, target, expected
):
    _linux_context(monkeypatch, tmp_path)
    (tmp_path / "localtime").symlink_to(target)
    (tmp_path / "timezone").write_text("FILE_MUST_NOT_WIN\n")
    monkeypatch.setenv("TZ", ":Pacific/Fiji")
    assert context.timezone_name() == expected


@pytest.mark.parametrize("localtime", [None, "unrecognized/zoneinfo/Asia/Tokyo"])
@pytest.mark.parametrize("contents", ["  Europe/Paris \r\n", ""])
def test_linux_timezone_file_preserves_leading_space_and_empty_success(
    tmp_path, monkeypatch, localtime, contents
):
    _linux_context(monkeypatch, tmp_path)
    if localtime is not None:
        (tmp_path / "localtime").symlink_to(localtime)
    (tmp_path / "timezone").write_bytes(contents.encode())
    assert context.timezone_name() == contents.rstrip()


@pytest.mark.parametrize(
    "config,expected",
    [
        ("config system\n option timezone 'CST-8'\n", "CST-8"),
        (
            'config system\n option timezone "CST-8"\n option zonename "Asia/Shanghai"\n',
            "Asia/Shanghai",
        ),
        (
            "# comment\nconfig other\n option zonename wrong\n"
            "config system\n option timezone UTC\n option zonename 'Europe/Paris'\n",
            "Europe/Paris",
        ),
        ("config system 'named'\n option zonename 'Asia/Shanghai'\n", None),
        ("config system\n option zonename 'unterminated\n", None),
        ("config system\n option zonename 'Asia/Tokyo' extra\n", None),
    ],
)
def test_linux_openwrt_fallback_uses_pinned_quoted_words_and_section_rules(
    tmp_path, monkeypatch, config, expected
):
    _linux_context(monkeypatch, tmp_path)
    (tmp_path / "timezone").write_bytes(b"\xff")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/system").write_text(config)
    assert context.timezone_name() == expected
