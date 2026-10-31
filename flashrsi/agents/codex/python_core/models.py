"""Model resolution ported from Codex rust-v0.147.0 (be6e8eac).

Sources: models-manager/src/{manager,model_info}.rs and
protocol/src/openai_models.rs. The bundled catalog and prompt are original
upstream bytes; they are runtime resources of this Python implementation.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path


def validate_model_settings(settings):
    # config_types.rs has closed enums except ReasoningEffort, whose custom
    # values deliberately accept future model-defined non-empty names.
    enums = {
        "model_reasoning_summary": {"auto", "concise", "detailed", "none"},
        "model_verbosity": {"low", "medium", "high"},
        "personality": {"none", "friendly", "pragmatic"},
    }
    for key, allowed in enums.items():
        value = settings.get(key)
        if value is not None and (not isinstance(value, str) or value not in allowed):
            raise ValueError(f"Invalid Codex {key}: {value!r}")
    effort = settings.get("model_reasoning_effort")
    if effort is not None and (not isinstance(effort, str) or not effort):
        raise ValueError("Codex model_reasoning_effort must be a non-empty string")


class Model:
    def __init__(self, model_name: str, settings: dict, assets_dir: Path | None = None):
        validate_model_settings(settings)
        self.assets_dir = assets_dir or Path(__file__).with_name("assets")
        catalog = json.loads((self.assets_dir / "models.json").read_text())["models"]
        base = (self.assets_dir / "prompt.md").read_text()
        # manager::construct_model_info_from_candidates: longest prefix first,
        # then strip exactly one simple provider namespace and retry.
        matches = [m for m in catalog if model_name.startswith(m["slug"])]
        if not matches and re.fullmatch(r"[A-Za-z0-9_-]+/[^/]+", model_name):
            suffix = model_name.split("/", 1)[1]
            matches = [m for m in catalog if suffix.startswith(m["slug"])]
        self.info = copy.deepcopy(
            max(matches, key=lambda m: len(m["slug"]))
            if matches
            else _fallback(model_name, base)
        )
        self.info["slug"] = model_name
        self.info["used_fallback_model_metadata"] = not bool(matches)
        # Defaults come from the ModelInfo serde schema, not an SDK model list.
        for key, value in {
            "supports_reasoning_summary_parameter": True,
            "default_reasoning_summary": "auto",
            "include_apps_usage_instructions": True,
            "include_plugin_usage_instructions": False,
            "effective_context_window_percent": 95,
            "input_modalities": ["text", "image"],
            "supports_image_detail_original": False,
            "use_responses_lite": False,
            "service_tiers": [],
        }.items():
            self.info.setdefault(key, value)
        self.settings = copy.deepcopy(settings)
        self._apply_overrides(settings)
        features = settings.get("features", {})
        if self.info.get("tool_mode") is None:

            def enabled(name):
                value = features.get(name, False)
                return value.get("enabled", False) if isinstance(value, dict) else value

            self.info["tool_mode"] = (
                "code_mode_only"
                if enabled("code_mode_only")
                else "code_mode"
                if enabled("code_mode")
                else None
            )
        messages = self.info.get("model_messages") or {}
        template = messages.get("instructions_template") or ""
        variables = messages.get("instructions_variables")
        if variables is not None:
            # config/mod.rs defaults enabled Personality to Pragmatic before
            # ModelInfo::get_model_instructions receives the resolved setting.
            personality = settings.get("personality") or "pragmatic"
            value = (
                ""
                if personality == "none"
                else variables.get("personality_" + personality)
            )
            template = template.replace("{{ personality }}", value or "")
        self.instructions = template

    def _apply_overrides(self, settings):
        # model_info::with_config_overrides, including byte vs token budgets.
        info = self.info
        if settings.get("model_context_window") is not None:
            window = settings["model_context_window"]
            info["context_window"] = min(
                window, info.get("max_context_window") or window
            )
        if settings.get("model_auto_compact_token_limit") is not None:
            info["auto_compact_token_limit"] = settings[
                "model_auto_compact_token_limit"
            ]
        if settings.get("tool_output_token_limit") is not None:
            policy = info["truncation_policy"]
            policy["limit"] = settings["tool_output_token_limit"] * (
                4 if policy["mode"] == "bytes" else 1
            )
        messages = info.setdefault("model_messages", {})
        if settings.get("base_instructions") is not None:
            messages["instructions_template"] = settings["base_instructions"]
            messages["instructions_variables"] = None
            return
        enabled = settings.get("features", {}).get("personality", True)
        template = messages.get("instructions_template")
        if enabled and settings.get("personality") == "none" and template:
            # strip_personality_section removes precisely one H1 section.
            lines = template.splitlines(keepends=True)
            start = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if line.rstrip("\r\n") == "# Personality"
                ),
                None,
            )
            if start is not None:
                end = next(
                    (
                        i
                        for i in range(start + 1, len(lines))
                        if re.match(r"^#(?:[ \t]|$)", lines[i].rstrip("\r\n"))
                    ),
                    len(lines),
                )
                messages["instructions_template"] = "".join(lines[:start] + lines[end:])
        if not enabled:
            local = info["used_fallback_model_metadata"] and info["slug"] in {
                "gpt-5.2-codex",
                "exp-codex-personality",
            }
            variables = messages.get("instructions_variables") or {}
            messages["instructions_template"] = (
                (self.assets_dir / "prompt.md").read_text()
                if local
                else (messages.get("instructions_template") or "").replace(
                    "{{ personality }}", variables.get("personality_default") or ""
                )
            )
            messages["instructions_variables"] = None

    @property
    def auto_compact_token_limit(self):
        # ModelInfo::auto_compact_token_limit, before the caller's effective
        # context-window percentage is applied to token accounting.
        window = self.info.get("context_window") or self.info.get("max_context_window")
        limit = self.info.get("auto_compact_token_limit")
        return (
            min(window * 9 // 10, limit)
            if window and limit is not None
            else window * 9 // 10
            if window
            else limit
        )


def _fallback(slug, base):
    # model_info::model_info_from_slug / local_model_messages_for_slug.
    variables = None
    if slug in {"gpt-5.2-codex", "exp-codex-personality"}:
        base = (
            "You are Codex, a coding agent based on GPT-5. You and the user share the same workspace and collaborate to achieve the user's goals.\n\n{{ personality }}\n\n"
            + base
        )
        variables = {
            "personality_default": "",
            "personality_friendly": "You optimize for team morale and being a supportive teammate as much as code quality.",
            "personality_pragmatic": "You are a deeply pragmatic, effective software engineer.",
        }
    return {
        "slug": slug,
        "display_name": slug,
        "description": None,
        "default_reasoning_level": None,
        "supported_reasoning_levels": [],
        "shell_type": "default",
        "visibility": "none",
        "supported_in_api": True,
        "priority": 99,
        "additional_speed_tiers": [],
        "service_tiers": [],
        "default_service_tier": None,
        "availability_nux": None,
        "upgrade": None,
        "model_messages": {
            "instructions_template": base,
            "instructions_variables": variables,
        },
        "include_skills_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "supports_reasoning_summary_parameter": True,
        "default_reasoning_summary": "auto",
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "web_search_tool_type": "text",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "supports_parallel_tool_calls": False,
        "supports_image_detail_original": False,
        "context_window": 272000,
        "max_context_window": 272000,
        "auto_compact_token_limit": None,
        "comp_hash": None,
        "effective_context_window_percent": 95,
        "experimental_supported_tools": [],
        "input_modalities": ["text", "image"],
        "supports_search_tool": False,
        "use_responses_lite": False,
        "auto_review_model_override": None,
        "model_specialty": None,
        "tool_mode": None,
        "multi_agent_version": None,
    }
