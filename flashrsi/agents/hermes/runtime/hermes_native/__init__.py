"""Snapshot-local Python implementation of Hermes's supported headless path."""

from .loop import NativeHermesResult, run

HERMES_BASELINE = "v0.22.5@bf0203a794a07aac3ff764972ab9087baa4e4f4e"

__all__ = ["HERMES_BASELINE", "NativeHermesResult", "run"]
