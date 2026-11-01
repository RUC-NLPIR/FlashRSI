"""Python port of Photon's image 0.24 Lanczos and PNG encoding path.

The codec tables and algorithms originate in image-rs/image 0.24.8,
image-rs/png 0.17.16 and image-rs/fdeflate 0.3.7 (MIT/Apache-2.0).
NumPy supplies explicitly rounded float32 array arithmetic, not an alternate
resampler. No Photon, WASM, Node or image command is invoked at runtime.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from pathlib import Path

import numpy as np

TABLES = json.loads(Path(__file__).with_name("image_codec_tables.json").read_text())


def _weights(old: int, new: int):
    f = np.float32
    ratio = f(f(old) / f(new))
    scale = max(f(1), ratio)
    support = f(f(3) * scale)
    pi = f(math.pi)

    def sinc(t):
        if t == 0:
            return f(1)
        a = f(t * pi)
        return f(f(math.sin(float(a))) / a)

    for position in range(new):
        centre = f(f(f(position) + f(0.5)) * ratio)
        left = max(0, min(old - 1, math.floor(f(centre - support))))
        right = max(left + 1, min(old, math.ceil(f(centre + support))))
        centre = f(centre - f(0.5))
        weights, total = [], f(0)
        for index in range(left, right):
            x = f(f(f(index) - centre) / scale)
            weight = f(sinc(x) * sinc(f(x / f(3)))) if abs(x) < 3 else f(0)
            weights.append(weight)
            total = f(total + weight)
        yield left, [f(weight / total) for weight in weights]


def resize_rgba(pixels: bytes, width: int, height: int, new_width: int, new_height: int):
    """image::imageops::resize: vertical float buffer, then rounded horizontal."""
    if (width, height) == (new_width, new_height):
        return pixels
    source = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)
    vertical = np.zeros((new_height, width, 4), dtype=np.float32)
    for y, (start, weights) in enumerate(_weights(height, new_height)):
        for offset, weight in enumerate(weights):
            vertical[y] += source[start + offset].astype(np.float32) * weight
    horizontal = np.zeros((new_height, new_width, 4), dtype=np.float32)
    for x, (start, weights) in enumerate(_weights(width, new_width)):
        for offset, weight in enumerate(weights):
            horizontal[:, x] += vertical[:, start + offset] * weight
    # Rust f32::round rounds ties away from zero; pixels are clamped first.
    return np.floor(np.clip(horizontal, 0, 255) + np.float32(0.5)).astype(np.uint8).tobytes()


def _deflate_codes(lengths):
    counts = [lengths.count(i) for i in range(max(lengths) + 1)]
    next_code, code = [0] * len(counts), 0
    for bits in range(1, len(counts)):
        code = (code + counts[bits - 1]) << 1
        next_code[bits] = code
    codes = []
    for size in lengths:
        value = next_code[size]
        next_code[size] += 1
        codes.append(int(f"{value:0{size}b}"[::-1], 2))
    return codes


class _FastDeflate:
    # fdeflate's fixed dynamic Huffman header, optimized for filtered PNGs.
    HEADER = bytes.fromhex(
        "7801edc003a0245996c6f1ff77ee8dc8cca7724b63ae6ddbb66ddbb66ddbb66d"
        "698c9e964aaf9e323322eef976b76a7aa6873b6bd50f"
    )

    def __init__(self):
        self.output = bytearray(self.HEADER[:-1])
        self.buffer, self.bits = self.HEADER[-1], 5
        self.checksum = 1
        self.lengths = TABLES["HUFFMAN_LENGTHS"]
        self.codes = _deflate_codes(self.lengths)

    def write(self, bits, count):
        self.buffer |= bits << self.bits
        self.bits += count
        while self.bits >= 8:
            self.output.append(self.buffer & 255)
            self.buffer >>= 8
            self.bits -= 8

    def literal(self, value):
        self.write(self.codes[value], self.lengths[value])

    def run(self, count):
        self.literal(0)
        count -= 1
        while count >= 258:
            self.write(self.codes[285], self.lengths[285] + 1)
            count -= 258
        if count > 4:
            symbol = TABLES["LENGTH_TO_SYMBOL"][count - 3]
            extra = TABLES["LENGTH_TO_LEN_EXTRA"][count - 3]
            self.literal(symbol)
            self.write((count - 3) & ((1 << extra) - 1), extra + 1)
        else:
            self.write(0, count * self.lengths[0])

    def append(self, data):
        self.checksum = zlib.adler32(data, self.checksum)
        count, complete = 0, len(data) // 8 * 8
        for index in range(0, complete, 8):
            chunk = data[index:index + 8]
            if chunk == b"\0" * 8:
                count += 8
                continue
            if count:
                prefix = len(chunk) - len(chunk.lstrip(b"\0"))
                self.run(count + prefix)
                count = 0
                if prefix:
                    count = len(chunk) - len(chunk.rstrip(b"\0"))
                    for value in chunk[prefix:8 - count]:
                        self.literal(value)
                    continue
            suffix = len(chunk) - len(chunk.rstrip(b"\0"))
            if suffix:
                for value in chunk[:8 - suffix]:
                    self.literal(value)
                count = suffix
            else:
                for value in chunk:
                    self.literal(value)
        if count:
            self.run(count)
        for value in data[complete:]:
            self.literal(value)

    def finish(self):
        self.literal(256)
        if self.bits:
            self.write(0, 8 - self.bits)
        return bytes(self.output) + struct.pack(">I", self.checksum & 0xFFFFFFFF)


def _stored_deflate(data):
    output = bytearray(b"\x78\x01")
    for offset in range(0, len(data), 65535):
        block = data[offset:offset + 65535]
        size = len(block)
        output.extend(struct.pack("<BHH", int(offset + size == len(data)), size, size ^ 65535))
        output.extend(block)
    output.extend(struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF))
    return bytes(output)


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(pixels: bytes, width: int, height: int):
    """RGBA8, adaptive PNG filters and fdeflate Fast, byte-for-byte as Photon."""
    source = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width * 4).astype(np.int16)
    previous = np.zeros(width * 4, dtype=np.int16)
    compressor = _FastDeflate()
    raw_lines = bytearray()
    for row in source:
        left = np.concatenate((np.zeros(4, dtype=np.int16), row[:-4]))
        upper_left = np.concatenate((np.zeros(4, dtype=np.int16), previous[:-4]))
        pa = np.abs(previous - upper_left)
        pb = np.abs(left - upper_left)
        pc = np.abs(left + previous - 2 * upper_left)
        paeth = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, previous, upper_left))
        predictors = (left, previous, (left + previous) // 2, paeth)
        best, best_score = None, math.inf
        for kind, prediction in enumerate(predictors, 1):
            values = (row - prediction).astype(np.uint8)
            score = np.abs(values.view(np.int8).astype(np.int16)).sum()
            if score <= best_score:
                best, best_score = bytes([kind]) + values.tobytes(), score
        compressor.append(best)
        raw_lines.extend(b"\0" + row.astype(np.uint8).tobytes())
        previous = row
    compressed = compressor.finish()
    # png::Encoder compares against the stored stream and disables filtering
    # completely when the filtered encoding is larger.
    stored_size = (max(0, len(raw_lines) - 1) // 65535) * 65540 + (len(raw_lines) % 65535 + 5) + 6
    if len(compressed) > stored_size:
        compressed = _stored_deflate(bytes(raw_lines))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + b"".join(_png_chunk(b"IDAT", compressed[i:i + 2**31 - 1]) for i in range(0, len(compressed), 2**31 - 1))
        + _png_chunk(b"IEND", b"")
    )


def _fdct_pass(samples, *, first):
    """IJG jfdctint row/column pass as translated by image 0.24.8."""
    output = np.empty_like(samples)
    t0 = samples[..., 0] + samples[..., 7]
    t1 = samples[..., 1] + samples[..., 6]
    t2 = samples[..., 2] + samples[..., 5]
    t3 = samples[..., 3] + samples[..., 4]
    t10 = t0 + t3 + (0 if first else 2)
    t12 = t0 - t3
    t11 = t1 + t2
    t13 = t1 - t2
    t0 = samples[..., 0] - samples[..., 7]
    t1 = samples[..., 1] - samples[..., 6]
    t2 = samples[..., 2] - samples[..., 5]
    t3 = samples[..., 3] - samples[..., 4]
    if first:
        output[..., 0] = (t10 + t11 - 1024) << 2
        output[..., 4] = (t10 - t11) << 2
    else:
        output[..., 0] = (t10 + t11) >> 2
        output[..., 4] = (t10 - t11) >> 2
    shift = 11 if first else 15
    z1 = (t12 + t13) * 4433 + (1 << (shift - 1))
    output[..., 2] = (z1 + t12 * 6270) >> shift
    output[..., 6] = (z1 - t13 * 15137) >> shift
    t12, t13 = t0 + t2, t1 + t3
    z1 = (t12 + t13) * 9633 + 1024
    t12, t13 = t12 * -3196 + z1, t13 * -16069 + z1
    z1 = (t0 + t3) * -7373
    t0, t3 = t0 * 12299 + z1 + t12, t3 * 2446 + z1 + t13
    z1 = (t1 + t2) * -20995
    t1, t2 = t1 * 25172 + z1 + t13, t2 * 16819 + z1 + t12
    for index, value in zip((1, 3, 5, 7), (t0, t1, t2, t3)):
        output[..., index] = value >> shift
    return output


def _jpeg_huffman(lengths, values):
    result, code, index = {}, 0, 0
    for size, count in enumerate(lengths, 1):
        for _ in range(count):
            result[values[index]] = code, size
            index += 1
            code += 1
        code <<= 1
    return result


class _JpegBits:
    def __init__(self):
        self.output, self.bits, self.buffer = bytearray(), 0, 0

    def write(self, value, count):
        if count == 0:
            return
        self.buffer = (self.buffer << count) | value
        self.bits += count
        while self.bits >= 8:
            self.bits -= 8
            byte = self.buffer >> self.bits
            self.buffer &= (1 << self.bits) - 1
            self.output.append(byte)
            if byte == 255:
                self.output.append(0)

    def coefficient(self, value, table, run=0):
        size = abs(value).bit_length()
        self.write(*table[(run << 4) | size])
        self.write((value - int(value < 0)) & ((1 << size) - 1), size)

    def block(self, block, previous, dc, ac):
        current = int(block[0])
        self.coefficient(current - previous, dc)
        run = 0
        for index in TABLES["UNZIGZAG"][1:]:
            value = int(block[index])
            if value == 0:
                run += 1
                continue
            while run > 15:
                self.write(*ac[0xF0])
                run -= 16
            self.coefficient(value, ac, run)
            run = 0
        if run:
            self.write(*ac[0])
        return current


def _jpeg_segment(marker, payload):
    return bytes([255, marker]) + struct.pack(">H", len(payload) + 2) + payload


def encode_jpeg(pixels: bytes, width: int, height: int, quality: int):
    """image::JpegEncoder RGBA8 path (4:4:4, IJG integer DCT)."""
    if not 0 < width < 65536 or not 0 < height < 65536:
        raise ValueError("JPEG dimensions must fit uint16")
    quality = max(1, min(100, quality))
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    qtables = [
        [max(1, min(255, (value * scale + 50) // 100)) for value in TABLES[name]]
        for name in ("STD_LUMA_QTABLE", "STD_CHROMA_QTABLE")
    ]
    output = bytearray(b"\xff\xd8")
    output.extend(_jpeg_segment(0xE0, b"JFIF\0\x01\x02\0\0\x01\0\x01\0\0"))
    output.extend(_jpeg_segment(0xC0, struct.pack(">BHHB", 8, height, width, 3) + bytes([1, 17, 0, 2, 17, 1, 3, 17, 1])))
    for identifier, table in enumerate(qtables):
        output.extend(_jpeg_segment(0xDB, bytes([identifier]) + bytes(table[i] for i in TABLES["UNZIGZAG"])))
    tables = []
    for channel, destination in (("LUMA", 0), ("CHROMA", 1)):
        for kind, class_id in (("DC", 0), ("AC", 1)):
            lengths = TABLES[f"STD_{channel}_{kind}_CODE_LENGTHS"]
            values = TABLES[f"STD_{channel}_{kind}_VALUES"]
            output.extend(_jpeg_segment(0xC4, bytes([(class_id << 4) | destination]) + bytes(lengths) + bytes(values)))
            tables.append(_jpeg_huffman(lengths, values))
    output.extend(_jpeg_segment(0xDA, bytes([3, 1, 0, 2, 17, 3, 17, 0, 63, 0])))
    source = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)[..., :3].astype(np.float32)
    r, g, b = (source[..., i] for i in range(3))
    f = np.float32
    # Keep the evaluation order and each float32 rounding of rgb_to_ycbcr.
    y = f(76.245) / f(255) * r + f(149.685) / f(255) * g + f(29.07) / f(255) * b
    cb = f(-43.0185) / f(255) * r - f(84.4815) / f(255) * g + f(127.5) / f(255) * b + f(128)
    cr = f(127.5) / f(255) * r - f(106.7685) / f(255) * g - f(20.7315) / f(255) * b + f(128)
    colors = np.clip(np.stack((y, cb, cr), axis=2), 0, 255).astype(np.uint8)
    del source, r, g, b, y, cb, cr
    colors = np.pad(colors, ((0, (-height) % 8), (0, (-width) % 8), (0, 0)), mode="edge")
    blocks = colors.reshape(colors.shape[0] // 8, 8, colors.shape[1] // 8, 8, 3).transpose(0, 2, 4, 1, 3).reshape(-1, 3, 8, 8)
    coefficients = _fdct_pass(_fdct_pass(blocks.astype(np.int64), first=True).swapaxes(-1, -2), first=False).swapaxes(-1, -2).reshape(-1, 3, 64)
    coefficients = np.sign(coefficients) * (np.abs(coefficients) // 8)
    quantized = coefficients.astype(np.float32) / np.asarray([qtables[0], qtables[1], qtables[1]], dtype=np.float32)
    quantized = (np.sign(quantized) * np.floor(np.abs(quantized) + f(0.5))).astype(np.int32)
    bits, previous = _JpegBits(), [0, 0, 0]
    for block in quantized:
        for channel in range(3):
            base = 0 if channel == 0 else 2
            previous[channel] = bits.block(block[channel], previous[channel], tables[base], tables[base + 1])
    bits.write(127, 7)
    output.extend(bits.output)
    output.extend(b"\xff\xd9")
    return bytes(output)


def _idct_kernel(s, offset, shift):
    """jpeg-decoder's scalar stb_image IDCT with wrapping int32 arithmetic."""
    def c(value):
        return int(np.float32(np.float32(value) * np.float32(4096)) + np.float32(0.5))

    s0, s1, s2, s3, s4, s5, s6, s7 = (s[..., i] for i in range(8))
    p1 = (s2 + s6) * c(0.5411961)
    t2 = p1 + s6 * c(-1.847759065)
    t3 = p1 + s2 * c(0.765366865)
    t0, t1 = (s0 + s4) << 12, (s0 - s4) << 12
    x0, x3, x1, x2 = t0 + t3 + offset, t0 - t3 + offset, t1 + t2 + offset, t1 - t2 + offset
    t0, t1, t2, t3 = s7, s5, s3, s1
    p3, p4, p1, p2 = t0 + t2, t1 + t3, t0 + t3, t1 + t2
    p5 = (p3 + p4) * c(1.175875602)
    t0, t1, t2, t3 = t0 * c(0.298631336), t1 * c(2.053119869), t2 * c(3.072711026), t3 * c(1.501321110)
    p1, p2 = p5 + p1 * c(-0.899976223), p5 + p2 * c(-2.562915447)
    p3, p4 = p3 * c(-1.961570560), p4 * c(-0.390180644)
    t3, t2, t1, t0 = t3 + p1 + p4, t2 + p2 + p3, t1 + p2 + p4, t0 + p1 + p3
    result = np.empty_like(s)
    for index, value in enumerate((x0 + t3, x1 + t2, x2 + t1, x3 + t0, x3 - t0, x2 - t1, x1 - t2, x0 - t3)):
        result[..., index] = value >> shift
    return result


def _jpeg_plane(coefficients, quantization):
    values = coefficients.astype(np.int32) * quantization.astype(np.int32)
    values = _idct_kernel(values.swapaxes(-1, -2), 512, 10).swapaxes(-1, -2)
    values = np.clip(_idct_kernel(values, 65536 + (128 << 17), 17), 0, 255).astype(np.uint8)
    return values.transpose(0, 2, 1, 3).reshape(values.shape[0] * 8, values.shape[1] * 8)


def _upsample_jpeg(plane, horizontal, vertical, width, height):
    plane = plane.astype(np.int32)
    if (horizontal, vertical) == (1, 1):
        return plane[:height, :width]
    if horizontal not in {1, 2} or vertical not in {1, 2}:
        return plane.repeat(vertical, axis=0).repeat(horizontal, axis=1)[:height, :width]
    # Component dimensions exclude padded IDCT block columns and rows.
    plane = plane[:math.ceil(height / vertical), :math.ceil(width / horizontal)]
    if vertical == 2:
        near = np.arange(height) // 2
        far = np.clip(near + np.where(np.arange(height) % 2, 1, -1), 0, plane.shape[0] - 1)
        plane = 3 * plane[near] + plane[far]
    if horizontal == 2:
        left = np.concatenate((plane[:, :1], plane[:, :-1]), axis=1)
        right = np.concatenate((plane[:, 1:], plane[:, -1:]), axis=1)
        scale = 4 if vertical == 2 else 2
        bias = 8 if vertical == 2 else 2
        output = np.empty((plane.shape[0], plane.shape[1] * 2), dtype=np.int32)
        output[:, ::2] = (3 * plane + left + bias) >> scale
        output[:, 1::2] = (3 * plane + right + bias) >> scale
        if vertical == 2:
            output[:, 0] = (plane[:, 0] + 2) >> 2
            output[:, -1] = (plane[:, -1] + 2) >> 2
        plane = output
    elif vertical == 2:
        plane = (plane + 2) >> 2
    return plane[:height, :width]


def decode_jpeg(data: bytes):
    """Read lossless JPEG coefficients, then use Photon's scalar decoder math."""
    from .jpeg_entropy import parse_jpeg

    image = parse_jpeg(data)
    coefficients = image.coefficients
    factors = np.asarray(image.sampling, dtype=np.int32)
    quantization = image.quantization
    quant_tbl_no = image.quant_tbl_no
    width, height = image.width, image.height
    color = image.color
    if coefficients:
        maximum = factors.max(axis=0)
        planes = [
            _upsample_jpeg(
                _jpeg_plane(component, quantization[quant_tbl_no[index]]),
                int(maximum[1] // factors[index, 1]),
                int(maximum[0] // factors[index, 0]),
                width, height,
            )
            for index, component in enumerate(coefficients)
        ]
    else:
        raise ValueError("JPEG contains no components")
    if len(planes) == 1:
        rgb = np.stack(planes * 3, axis=2)
    elif color == "JCS_RGB":
        rgb = np.stack(planes[:3], axis=2)
    elif color == "JCS_YCbCr":
        y, cb, cr = planes
        y = y * (1 << 20) + (1 << 19)
        cb, cr = cb - 128, cr - 128

        def coefficient(value):
            return int(np.float32(np.float32(value) * np.float32(1 << 20)) + np.float32(0.5))

        rgb = np.stack((
            (y + coefficient(1.402) * cr) >> 20,
            (y - coefficient(0.34414) * cb - coefficient(0.71414) * cr) >> 20,
            (y + coefficient(1.772) * cb) >> 20,
        ), axis=2)
    elif color == "JCS_CMYK":
        c, m, y, k = planes
        rgb = np.stack(((k * c) // 255, (k * m) // 255, (k * y) // 255), axis=2)
    elif color == "JCS_YCCK":
        c, m, y, k = planes
        c, m, y = c * (1 << 20) + (1 << 19), m - 128, y - 128
        rgb = np.stack(
            (
                (c + coefficient(1.402) * y) >> 20,
                (c - coefficient(0.34414) * m - coefficient(0.71414) * y) >> 20,
                (c + coefficient(1.772) * m) >> 20,
            ),
            axis=2,
        )
        alpha = 255 - k
    else:
        raise ValueError(f"Unsupported JPEG color transform: {color}")
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255)
    rgba[..., 3] = alpha if "alpha" in locals() else 255
    return rgba.tobytes(), width, height


def _riff_chunks(data: bytes):
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return []
    result, offset = [], 12
    while offset + 8 <= len(data):
        kind, size = data[offset:offset + 4], int.from_bytes(data[offset + 4:offset + 8], "little")
        payload = data[offset + 8:offset + 8 + size]
        if len(payload) != size:
            break
        result.append((kind, payload))
        offset += 8 + size + (size & 1)
    return result


def decode_webp_lossy(data: bytes):
    """Decode VP8 and VP8X/VP8 lossy frames with the image-rs port.

    Extended WebP's ``ALPH`` chunk stores a predictor-coded alpha plane.  The
    common Pillow encoder path uses the uncompressed alpha form (compression
    bits zero); keeping this small decoder here avoids routing the image
    through a different codec and preserves image-rs' VP8 pixel values.
    """
    chunks = _riff_chunks(data)
    vp8 = next((payload for kind, payload in chunks if kind == b"VP8 "), None)
    if vp8 is None:
        return None
    from .vp8_decoder import Vp8Decoder

    pixels, width, height = Vp8Decoder(vp8).decode()
    alph = next((payload for kind, payload in chunks if kind == b"ALPH"), None)
    if alph is None:
        return pixels, width, height
    if not alph:
        raise ValueError("Empty WebP alpha chunk")
    info = alph[0]
    # Bits 7..6 are reserved; bits 5..4 are preprocessing, bits 3..2 pick
    # the predictor, and bits 1..0 select raw versus lossless compression.
    if info & 0xC0 or (info >> 4) & 0x03 > 1:
        raise ValueError("Unsupported WebP alpha info bits")
    filtering = (info >> 2) & 0x03
    compression = info & 0x03
    if compression == 1:
        # VP8L alpha requires the full image-rs lossless decoder.  Returning
        # None lets the caller use its existing lossless-image fallback.
        return None
    if compression != 0:
        raise ValueError("Unsupported WebP alpha compression")
    alpha = alph[1:]
    if len(alpha) != width * height:
        raise ValueError("WebP alpha chunk size mismatch")
    rgba = bytearray(pixels)

    def predictor(x, y):
        if filtering == 0:
            return 0
        if filtering == 1:  # horizontal
            if x == 0 and y == 0:
                return 0
            index = (y - 1) * width if x == 0 else y * width + x - 1
            return rgba[index * 4 + 3]
        if filtering == 2:  # vertical
            if x == 0 and y == 0:
                return 0
            index = y * width + x - 1 if y == 0 else (y - 1) * width + x
            return rgba[index * 4 + 3]
        # Gradient predictor, with the same edge handling as image-rs.
        if x == 0 and y == 0:
            left = top = top_left = 0
        elif x == 0:
            left = top = top_left = rgba[((y - 1) * width) * 4 + 3]
        elif y == 0:
            left = top = top_left = rgba[(y * width + x - 1) * 4 + 3]
        else:
            left = rgba[(y * width + x - 1) * 4 + 3]
            top = rgba[((y - 1) * width + x) * 4 + 3]
            top_left = rgba[((y - 1) * width + x - 1) * 4 + 3]
        return max(0, min(255, left + top - top_left))

    for y in range(height):
        for x in range(width):
            index = y * width + x
            rgba[index * 4 + 3] = (predictor(x, y) + alpha[index]) & 0xFF
    return bytes(rgba), width, height
