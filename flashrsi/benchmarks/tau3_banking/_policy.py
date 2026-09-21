"""Render a tau2 agent policy from the domain's own prompt templates.

The domain ships one prompt template per retrieval variant, plus reusable
components. Upstream assembles the agent policy by expanding
``{{component:NAME}}`` and, for two variants, inlining knowledge-base content.
This module reproduces that assembly so the policy an Agent receives is the
domain's own text rather than something written here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Variant -> template, mirroring the upstream retrieval variant registry. The
# variant also selects the agent's tools, which arrive with the simulator; only
# the policy text is reproduced here.
_VARIANTS = {
    "alltools": "all_tools.md",
    "no_knowledge": "no_knowledge.md",
    "full_kb": "full_kb.md",
    "golden_retrieval": "required_docs.md",
    "grep_only": "grep_only.md",
    "terminal_use": "agentic_search.md",
    "terminal_use_write": "agentic_search_write.md",
    "bm25": "classic_rag_bm25_no_grep.md",
    "bm25_reranker": "classic_rag_bm25_no_grep.md",
    "bm25_grep": "classic_rag_bm25.md",
    "bm25_reranker_grep": "classic_rag_bm25.md",
    "qwen_embeddings": "classic_rag_qwen_no_grep.md",
    "qwen_embeddings_reranker": "classic_rag_qwen_no_grep.md",
    "qwen_embeddings_grep": "classic_rag_qwen.md",
    "qwen_embeddings_reranker_grep": "classic_rag_qwen.md",
    "openai_embeddings": "classic_rag_openai_no_grep.md",
    "openai_embeddings_reranker": "classic_rag_openai_no_grep.md",
    "openai_embeddings_grep": "classic_rag_openai.md",
    "openai_embeddings_reranker_grep": "classic_rag_openai.md",
}
# Upstream's own default variant.
_DEFAULT_VARIANT = "alltools"
_COMPONENT = re.compile(r"\{\{component:(\w+)\}\}")


def _variants() -> tuple[str, ...]:
    return tuple(sorted(_VARIANTS))


def _policy(domain: Path, variant: str, required_documents: tuple[str, ...]) -> str:
    """Return the agent policy for one task under ``variant``.

    ``{{full_knowledge_base}}`` and ``{{required_documents}}`` are filled from
    the domain's documents, as upstream's full_kb and golden_retrieval variants
    do. Any other placeholder is left in place: it is filled by the simulator
    at run time and inventing a value here would misstate the policy.
    """
    try:
        template = _VARIANTS[variant]
    except KeyError:
        raise ValueError(
            f"Unknown tau3 Banking retrieval variant: {variant!r}; "
            f"available: {', '.join(_variants())}"
        ) from None
    path = domain / "prompts" / template
    if not path.is_file():
        raise ValueError(f"tau3 Banking domain is missing {path.name}")

    text = _COMPONENT.sub(
        lambda m: _component(domain, m.group(1)), path.read_text("utf-8")
    )
    if "{{full_knowledge_base}}" in text:
        text = text.replace("{{full_knowledge_base}}", _documents(domain, None))
    if "{{required_documents}}" in text:
        text = text.replace(
            "{{required_documents}}", _documents(domain, required_documents)
        )
    return text


def _component(domain: Path, name: str) -> str:
    path = domain / "prompts" / "components" / f"{name}.md"
    if not path.is_file():
        raise ValueError(f"tau3 Banking domain is missing component: {name}")
    return path.read_text("utf-8")


def _documents(domain: Path, wanted: tuple[str, ...] | None) -> str:
    """Format documents as upstream does, by title then id, joined by rules."""
    documents = {}
    for path in sorted((domain / "documents").glob("*.json")):
        value = json.loads(path.read_text("utf-8"))
        title, content = value.get("title"), value.get("content")
        if not isinstance(title, str) or not isinstance(content, str):
            raise ValueError(f"tau3 Banking document is malformed: {path.name}")
        documents[value.get("id", path.stem)] = (title, content)
    if wanted is None:
        selected = list(documents.values())
    else:
        by_title = {title: (title, content) for title, content in documents.values()}
        # Upstream resolves a reference by title first, then by id, and skips
        # anything it cannot find rather than failing the task.
        selected = [
            by_title[reference] if reference in by_title else documents[reference]
            for reference in wanted
            if reference in by_title or reference in documents
        ]
    return "\n\n---\n\n".join(f"## {title}\n\n{content}" for title, content in selected)
