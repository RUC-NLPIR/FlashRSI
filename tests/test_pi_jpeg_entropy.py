"""Pure Python JPEG entropy coefficients against the pinned libjpeg oracle."""

import io

import numpy as np
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.jpeg_entropy import parse_jpeg

jpeglib = pytest.importorskip("jpeglib")
Image = pytest.importorskip("PIL.Image")


def _jpeg(mode, width, height, *, progressive, restart, quality=73):
    values = np.arange(width * height * len(mode), dtype=np.uint8)
    shape = (height, width, len(mode)) if len(mode) > 1 else (height, width)
    image = Image.fromarray(values.reshape(shape), mode)
    output = io.BytesIO()
    options = {
        "format": "JPEG",
        "quality": quality,
        "progressive": progressive,
    }
    if mode == "RGB":
        options["subsampling"] = 2
    if restart:
        options["restart_marker_blocks"] = restart
    image.save(output, **options)
    return output.getvalue()


def _oracle_coefficients(data):
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jpg") as stream:
        stream.write(data)
        stream.flush()
        image = jpeglib.read_dct(stream.name)
    components = [image.Y]
    if image.has_chrominance:
        components.extend((image.Cb, image.Cr))
    if image.has_black:
        components.append(image.K)
    return image, components


@pytest.mark.parametrize("mode", ["L", "RGB", "CMYK"])
@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("restart", [0, 3])
def test_native_entropy_matches_libjpeg_for_sampling_progressive_and_restart(
    mode, progressive, restart
):
    data = _jpeg(
        mode,
        37,
        29,
        progressive=progressive,
        restart=restart,
    )
    native = parse_jpeg(data)
    oracle, components = _oracle_coefficients(data)
    assert (native.width, native.height) == (oracle.width, oracle.height)
    assert native.color == str(oracle.jpeg_color_space)
    assert native.sampling == [
        (int(vertical), int(horizontal)) for vertical, horizontal in oracle.samp_factor
    ]
    assert native.quant_tbl_no == [int(value) for value in oracle.quant_tbl_no]
    assert len(native.coefficients) == len(components)
    for decoded, expected in zip(native.coefficients, components):
        np.testing.assert_array_equal(decoded, expected)
    for index, expected in enumerate(oracle.qt):
        np.testing.assert_array_equal(native.quantization[index], expected)


def test_native_entropy_keeps_progressive_dc_and_ac_refinements():
    data = _jpeg("RGB", 83, 61, progressive=True, restart=5, quality=91)
    native = parse_jpeg(data)
    _, components = _oracle_coefficients(data)
    for decoded, expected in zip(native.coefficients, components):
        np.testing.assert_array_equal(decoded, expected)
        assert np.any(decoded[..., 0] != 0)
        assert np.any(decoded[..., 1:] != 0)


@pytest.mark.parametrize(
    "data",
    [b"", b"\x00\x01", b"\xff\xd8\xff\xd9", b"\xff\xd8\xff\xc0\x00\x02"],
)
def test_native_entropy_rejects_truncated_or_invalid_jpeg(data):
    with pytest.raises((TypeError, ValueError)):
        parse_jpeg(data)


def test_native_entropy_requires_bytes():
    with pytest.raises(TypeError):
        parse_jpeg("not bytes")
