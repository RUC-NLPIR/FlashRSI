"""Run the pinned official evaluator with a task-local independent LLM client."""

import copy
import json
from asyncio import CancelledError

from flashrsi.benchmarks.widesearch import METRICS, _scores


class _JudgeError(ValueError):
    """Keep completed SDK evidence when native evaluation rejects a response."""

    def __init__(self, message, usage, responses):
        super().__init__(message)
        self.usage = usage
        self.responses = responses


def evaluate(query, prediction, config, *, cancelled=None):
    from openai import DefaultHttpxClient, OpenAI

    from flashrsi.benchmarks.widesearch._vendor._llm import completion
    from flashrsi.benchmarks.widesearch._vendor.data_loader import WideSearchResponse
    from flashrsi.benchmarks.widesearch._vendor.evaluation import evaluate_single_query

    def check_cancelled(_request=None):
        if cancelled is not None and cancelled.is_set():
            # BaseException bypasses both the SDK's retries and the official
            # evaluator's broad Exception-to-zero fallback.
            raise CancelledError

    check_cancelled()
    llm = json.loads(json.dumps(config["llm"], default=dict))
    model = llm.pop("model_name")
    key = llm.pop("api_key")
    url = llm.pop("base_url", None) or "https://api.openai.com/v1"
    if "max_completion_tokens" not in llm:
        llm.setdefault("max_tokens", 10240)
    usage = {"requests": 0}
    responses = []
    failures = []
    with (
        DefaultHttpxClient(
            # SDK retries issue additional HTTP requests inside a single completion.
            # Check at transport entry as well as at the evaluator callback boundary.
            event_hooks={"request": [check_cancelled]},
        ) as http_client,
        OpenAI(
            api_key=key,
            base_url=url,
            timeout=config["timeout"],
            max_retries=config.get("max_retries", 1),
            http_client=http_client,
        ) as client,
    ):

        def call(messages):
            check_cancelled()
            try:
                response = client.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": messages}], **llm
                )
                # A truncated response is still a completed, billed SDK call.
                # Missing SDK counters stay absent rather than becoming zero.
                usage["requests"] += 1
                tokens = None
                if response.usage is not None:
                    tokens = {}
                    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = getattr(response.usage, name, None)
                        if value is not None:
                            tokens[name] = value
                            usage[name] = usage.get(name, 0) + value
                responses.append(
                    {
                        "choices": [
                            {
                                "finish_reason": choice.finish_reason,
                                "content": choice.message.content,
                            }
                            for choice in response.choices
                        ],
                        "usage": tokens,
                    }
                )
                check_cancelled()
                if not response.choices or response.choices[0].finish_reason != "stop":
                    raise ValueError("Incomplete WideSearch judge response")
            except Exception:
                failures.append(True)
                raise
            return response.choices[0].message

        token = completion.set(call)
        try:
            result = evaluate_single_query(
                copy.deepcopy(query), WideSearchResponse(query.instance_id, prediction)
            )
        except Exception as exc:
            raise _JudgeError(
                f"WideSearch evaluator failed ({type(exc).__name__})", usage, responses
            ) from exc
        finally:
            completion.reset(token)
    if failures:
        raise _JudgeError("WideSearch judge request failed", usage, responses)
    check_cancelled()
    try:
        scores = _scores({k: float(getattr(result, k)) for k in METRICS})
    except Exception as exc:
        raise _JudgeError(
            f"WideSearch evaluator failed ({type(exc).__name__})", usage, responses
        ) from exc
    return scores, usage
