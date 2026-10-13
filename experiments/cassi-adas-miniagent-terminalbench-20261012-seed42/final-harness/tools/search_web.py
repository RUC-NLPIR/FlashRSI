"""Safe wrapper around the base web search service.

Unlike listing the built-in web_search tool in agent.yaml, this wrapper does not
trigger the workspace loader's mandatory endpoint preflight. If web access is
configured, the model gets normal search results; if it is not configured, the
model gets a clean, non-fatal error and can fall back to other tools instead of
the whole run crashing before the first LLM call.
"""

from __future__ import annotations

import types


async def call(args, ctx) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    query = query.strip()
    try:
        from runtime import tools as web_tools

        text, items = await web_tools.web_search_structured(query)
    except Exception as e:
        return (
            f"[search_web] search unavailable: {type(e).__name__}: {e}. "
            "You may use shell or answer from general knowledge, but clearly mark "
            "any factual claim that you could not verify."
        )

    # Keep the runtime's structured search history consistent even though this
    # is a workspace-provided tool rather than the built-in web_search.
    try:
        search_calls = getattr(ctx, "search_calls", 0) + 1
        setattr(ctx, "search_calls", search_calls)
        trace = getattr(ctx, "trace", None)
        if trace is not None:
            try:
                trace.save_search(search_calls, query, text)
            except Exception:
                pass
        urls = [item.get("url") for item in items if isinstance(item, dict)]
        searches = getattr(ctx, "searches", None)
        if searches is not None:
            searches.append(types.SimpleNamespace(urls=urls))
    except Exception:
        pass

    return text
