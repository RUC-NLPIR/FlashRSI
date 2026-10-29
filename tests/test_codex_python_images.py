"""Image history preparation keeps original accepted bytes and native errors."""

import asyncio
import base64
import io

import pytest
from PIL import Image
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.compact import estimate_item_tokens
from flashrsi.agents.codex.python_core.images import (
    UnsupportedImage,
    output_dimensions,
    prepare_image,
)


def _encoded_image(format_name, size=(8, 5)):
    image = Image.new("RGB", size, (200, 30, 80))
    output = io.BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


@pytest.mark.parametrize("format_name", ["PNG", "JPEG", "WEBP"])
def test_native_image_history_request_parity(
    format_name, parity_source, upstream_codex, tmp_path
):
    task = tmp_path / "task"
    task.mkdir()
    image_path = task / "image"
    data = _encoded_image(format_name)
    image_path.write_bytes(data)
    traces = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset(
                [
                    (
                        200,
                        _events(
                            call=("view_image", {"path": "image"}),
                            response_id="resp_image",
                        ),
                    ),
                    (200, _events()),
                ]
            )
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "sandbox": "danger-full-access",
                "timeout": 30,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Inspect the supplied image.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert len(replay.requests) == 2 and not replay.errors and not replay.steps
            outputs = [
                item
                for item in replay.requests[1]["body"]["input"]
                if item["type"] == "function_call_output"
            ]
            url = outputs[-1]["output"][0]["image_url"]
            assert url.startswith("data:image/")
            assert base64.b64decode(url.split(",", 1)[1]) == data
            traces.append(_normalize(replay.requests, tmp_path))
    assert traces[0] == traces[1]


@pytest.mark.parametrize(
    "url,detail,fragment",
    [
        ("https://example.invalid/image.png", "high", "remote image URLs"),
        ("data:image/png;base64,bad", "high", "could not be processed"),
        ("data:image/png;base64,bad", "low", "detail 'low' is not supported"),
    ],
)
def test_native_invalid_image_placeholders(url, detail, fragment):
    result = prepare_image({"type": "input_image", "image_url": url, "detail": detail})
    assert result["type"] == "input_text" and fragment in result["text"]


def test_valid_images_requiring_unported_encoding_reject_explicitly():
    url = (
        "data:application/octet-stream;base64,"
        + base64.b64encode(_encoded_image("TIFF")).decode()
    )
    with pytest.raises(UnsupportedImage, match="TIFF to PNG re-encoding"):
        prepare_image({"type": "input_image", "image_url": url})
    url = (
        "data:image/png;base64,"
        + base64.b64encode(_encoded_image("PNG", (2049, 2))).decode()
    )
    with pytest.raises(UnsupportedImage, match="Triangle image resizing"):
        prepare_image({"type": "input_image", "image_url": url})


def test_native_patch_budget_dimension_rules():
    assert output_dimensions(4000, 4000, 2048, 2500) == (1600, 1600)
    assert output_dimensions(6000, 6000, 6000, 10000) == (3200, 3200)
    assert output_dimensions(4096, 1024, 2048, 2500) == (2048, 512)


def test_original_image_estimation_uses_dimensions_and_high_uses_native_constant():
    data = _encoded_image("PNG", (64, 32))
    url = "data:image/png;base64," + base64.b64encode(data).decode()
    item = {
        "type": "function_call_output",
        "call_id": "c",
        "output": [{"type": "input_image", "image_url": url, "detail": "original"}],
    }
    original = estimate_item_tokens(item)
    item["output"][0]["detail"] = "high"
    high = estimate_item_tokens(item)
    assert high > original + 1800
