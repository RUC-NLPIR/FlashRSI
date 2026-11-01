from ..upstream_pricing.urls import base_url_host_matches,base_url_hostname

def _anthropic_preserve_dots(self) -> bool:
    """True for anthropic-compatible endpoints that keep dots in model names (DashScope, MiniMax, Xiaomi
    MiMo, OpenCode Go/Zen, ZAI/Zhipu; Bedrock's dotted inference-profile IDs 400 on the hyphenated form).

    Alibaba/DashScope keeps dots (e.g. qwen3.5-plus). OpenCode Go/Zen keeps dots for non-Claude models
    (e.g. minimax-m2.5-free). ``global.anthropic.claude-opus-4-7``,
    ``us.anthropic.claude-sonnet-4-5-20250929-v1:0``) and rejects the hyphenated form with ``HTTP 400
    The provided model identifier is invalid``. Regression for #11976; mirrors the opencode-go fix for
    #5211
    """
    if (getattr(self, "provider", "") or "").lower() in {
        "alibaba", "minimax", "minimax-cn", "opencode-go", "opencode-zen", "zai", "bedrock", "xiaomi", "vertex",
    }:
        return True
    base = (getattr(self, "base_url", "") or "").lower()
    host = base_url_hostname(base)
    return (
        "dashscope" in host
        or base_url_host_matches(base, "aliyuncs.com")
        or "minimax" in host
        or (base_url_host_matches(base, "opencode.ai") and "/zen/" in base)
        or base_url_host_matches(base, "bigmodel.cn")
        or base_url_host_matches(base, "xiaomimimo.com")
        # Vertex AI OpenAI-compat endpoint — Gemini model ids keep dots
        # (e.g. google/gemini-3.5-flash); the hyphenated form is wrong.
        or base_url_host_matches(base, "aiplatform.googleapis.com")
        # AWS Bedrock runtime endpoints — defense-in-depth when
        # ``provider`` is unset but ``base_url`` still names Bedrock.
        or host.startswith("bedrock-runtime.")
    )

