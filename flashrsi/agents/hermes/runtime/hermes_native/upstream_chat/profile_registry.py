"""Snapshot-local registry populated only by the pinned HTTP profiles."""

profiles = {}

def register_provider(profile):
    for name in (profile.name, *profile.aliases):
        profiles[name] = profile

def load_profiles():
    from .profiles import actual  # noqa: F401
    from .profiles import ai_gateway  # noqa: F401
    from .profiles import alibaba  # noqa: F401
    from .profiles import alibaba_coding_plan  # noqa: F401
    from .profiles import arcee  # noqa: F401
    from .profiles import azure_foundry  # noqa: F401
    from .profiles import copilot  # noqa: F401
    from .profiles import deepinfra  # noqa: F401
    from .profiles import fireworks  # noqa: F401
    from .profiles import gmi  # noqa: F401
    from .profiles import huggingface  # noqa: F401
    from .profiles import kilocode  # noqa: F401
    from .profiles import lmstudio  # noqa: F401
    from .profiles import meta_ai  # noqa: F401
    from .profiles import minimax  # noqa: F401
    from .profiles import nebius_token_factory  # noqa: F401
    from .profiles import nous  # noqa: F401
    from .profiles import novita  # noqa: F401
    from .profiles import nvidia  # noqa: F401
    from .profiles import ollama_cloud  # noqa: F401
    from .profiles import opencode_zen  # noqa: F401
    from .profiles import qwen_oauth  # noqa: F401
    from .profiles import stepfun  # noqa: F401
    from .profiles import tencent_tokenhub  # noqa: F401
    from .profiles import upstage  # noqa: F401
    from .profiles import xiaomi  # noqa: F401
    from .profiles import zai  # noqa: F401
    return profiles
