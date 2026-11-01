"""Original models.dev lookup against the exact catalog shipped with Snapshot."""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"


def generate(source, catalog_path):
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() == PIN
    sys.path.insert(0, str(source))
    raw = gzip.decompress(catalog_path.read_bytes())
    catalog = json.loads(raw)

    def deny(*args, **kwargs):
        raise RuntimeError("offline catalog oracle prohibits network")

    socket.socket.connect = deny
    socket.create_connection = deny
    from agent import models_dev
    from agent.image_routing import _supports_vision_override
    from hermes_cli import config as config_module

    cases = []
    with patch.object(models_dev, "fetch_models_dev", return_value=catalog), patch.object(config_module, "load_config_readonly", return_value={}):
        def add(provider, model, settings=None):
            settings = settings or {}
            caps = models_dev.get_model_capabilities(provider, model, config=settings)
            info = models_dev.get_model_info(provider, model, config=settings)
            with patch.object(config_module, "load_config_readonly", return_value=settings):
                ctx = models_dev.lookup_models_dev_context(provider, model)
            cases.append(dict(provider=provider, model=model, settings=settings,
                              caps=dataclasses.asdict(caps) if caps else None,
                              info=dataclasses.asdict(info) if info else None,
                              context=ctx,
                              vision_override=_supports_vision_override(settings, provider, model)))

        for provider, mdev_id in models_dev.PROVIDER_TO_MODELS_DEV.items():
            rows = sorted(catalog.get(mdev_id, {}).get("models", {}))
            if not rows:
                continue
            step = max(1, len(rows)//8)
            for model in rows[::step][:9]:
                add(provider, model)
                add(provider, model.upper())
        for provider, model in (("custom", "unknown"), ("deepseek", "deepseek-v4-flash-vision-exp"), ("openai", "gpt-6-astra"), ("opencode-go-bridge", "vendor-new-vision-exp"), ("openrouter", "openai/gpt-4o:nitro"), ("openrouter", "openai/gpt-4o:free"), ("ollama-cloud", "kimi-k2.5")):
            add(provider,model)
        for settings in (
            {"model_overrides": {"openai": {"gpt-4o": {"context_window": 12345, "supports_vision": False}}}},
            {"model_overrides": {"openai": {"_default": {"context_window": 12345, "supports_vision": False}}}},
            {"model": {"supports_vision": "false"}},
            {"model": {"supports_vision": "yes"}},
            {"providers": {"openai": {"models": {"gpt-4o": {"supports_vision": "false"}}}}},
        ):
            add("openai", "gpt-4o", settings)
            add("openai", "missing-fixture", settings)
        for settings in (
            {"providers": {"custom:relay": {"catalog_provider": "openai"}}},
            {"custom_providers": [{"name": "relay", "catalog_provider": "openai"}]},
        ):
            add("custom:relay", "gpt-4o", settings)
    return dict(commit=PIN,catalog_sha256=hashlib.sha256(raw).hexdigest(),cases=cases,
                source_sha256=hashlib.sha256((source/'agent/models_dev.py').read_bytes()).hexdigest())


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--catalog',type=Path,default=Path(__file__).parents[2]/'flashrsi/agents/hermes/runtime/hermes_native/upstream_catalog/models_dev.json.gz')
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('hermes_catalog_upstream.json'))
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hermes-catalog-oracle-') as home:
        os.environ['HERMES_HOME']=home
        args.output.write_text(json.dumps(generate(args.source,args.catalog),indent=2,ensure_ascii=False)+'\n')
