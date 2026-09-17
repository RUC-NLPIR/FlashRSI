"""Detach configuration and redact credentials in persisted runtime records."""

import json
from collections.abc import Mapping
from pathlib import Path

import yaml


def _credential_key(key):
    name = str(key).upper().replace("-", "_")
    return name.endswith(("API_KEY", "TOKEN", "SECRET", "PASSWORD")) or name in {
        "AUTHORIZATION",
        "PROXY_AUTHORIZATION",
        "COOKIE",
        "SET_COOKIE",
    }


def _secrets(value):
    """Collect credential strings from environment or nested configuration."""
    found = set()

    def visit(item, credential=False):
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, credential or _credential_key(key))
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, credential)
        elif credential and isinstance(item, str) and item:
            found.add(item)

    visit(value)
    return sorted(found, key=len, reverse=True)


def _redact(value, secrets):
    """Redact text and JSON records without changing their structure."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, Mapping):
        return {
            _redact(key, secrets): _redact(item, secrets) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    return value


def _redact_config(value):
    """Make a detached YAML config; credential fields reload as unset."""

    def clean(item):
        if isinstance(item, Mapping):
            return {
                key: None if _credential_key(key) else clean(child)
                for key, child in item.items()
            }
        if isinstance(item, (list, tuple)):
            return [clean(child) for child in item]
        if isinstance(item, Path):
            return str(item)
        return item

    return _redact(clean(value), _secrets(value))


def _config_record(value):
    """Keep JSON values directly; tag other safe YAML values for trace storage."""
    return json.loads(
        json.dumps(
            _redact_config(value),
            default=lambda item: {"type": "yaml", "value": yaml.safe_dump(item)},
        )
    )
