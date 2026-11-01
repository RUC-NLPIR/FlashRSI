"""Pure Python source port of image 0.24.8's VP8 keyframe decoder.

This deliberately preserves that decoder's prediction borders and loop filter
rounding, which differ from libwebp. Original image-rs sources are licensed
MIT/Apache-2.0; see IMAGE_CODECS_UPSTREAM.md.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

T = json.loads(Path(__file__).with_name("vp8_tables.json").read_text())


def clamp(value, low=0, high=255):
    return max(low, min(high, value))


class BoolReader:
    def __init__(self, data):
        if len(data) < 2:
            raise ValueError("Not enough VP8 partition data")
        self.data, self.index = data, 2
        self.value, self.range, self.count = (data[0] << 8) | data[1], 255, 0

    def boolean(self, probability=128):
        split = 1 + (((self.range - 1) * probability) >> 8)
        result = self.value >= split << 8
        if result:
            self.range -= split
            self.value -= split << 8
        else:
            self.range = split
        while self.range < 128:
            self.value = (self.value << 1) & 0xFFFFFFFF
            self.range <<= 1
            self.count += 1
            if self.count == 8:
                self.count = 0
                if self.index < len(self.data):
                    self.value |= self.data[self.index]
                    self.index += 1
        return result

    def literal(self, bits):
        result = 0
        for _ in range(bits):
            result = (result << 1) | self.boolean()
        return result

    def signed(self, bits):
        magnitude = self.literal(bits)
        return -magnitude if self.boolean() else magnitude

    def tree(self, tree, probabilities, start=0):
        index = start
        while True:
            index = tree[index + self.boolean(probabilities[index >> 1])]
            if index <= 0:
                return -index


@dataclass
class MacroBlock:
    bpred: list[int] = field(default_factory=lambda: [0] * 16)
    complexity: list[int] = field(default_factory=lambda: [0] * 9)
    luma: int = 0
    chroma: int = 0
    segment: int = 0
    skipped: bool = False


@dataclass
class Segment:
    delta: bool = False
    quantizer: int = 0
    filter: int = 0
    ydc: int = 0
    yac: int = 0
    y2dc: int = 0
    y2ac: int = 0
    uvdc: int = 0
    uvac: int = 0


def idct(block):
    for axis in range(2):
        for i in range(4):
            indices = [i + 4 * j for j in range(4)] if axis == 0 else [4 * i + j for j in range(4)]
            s0, s1, s2, s3 = (block[j] for j in indices)
            a, b = s0 + s2, s0 - s2
            c = ((s1 * 35468) >> 16) - s3 - ((s3 * 20091) >> 16)
            d = s1 + ((s1 * 20091) >> 16) + ((s3 * 35468) >> 16)
            values = [a + d, b + c, b - c, a - d]
            if axis:
                values = [(value + 4) >> 3 for value in values]
            for index, value in zip(indices, values):
                block[index] = value


def iwht(block):
    for axis in range(2):
        for i in range(4):
            indices = [i + 4 * j for j in range(4)] if axis == 0 else [4 * i + j for j in range(4)]
            s0, s1, s2, s3 = (block[j] for j in indices)
            a, b, c, d = s0 + s3, s1 + s2, s1 - s2, s0 - s3
            values = [a + b, c + d, a - b, d - c]
            if axis:
                values = [(value + 3) >> 3 for value in values]
            for index, value in zip(indices, values):
                block[index] = value


class Vp8Decoder:
    def __init__(self, data):
        self.data = data
        self.segments = [Segment() for _ in range(4)]
        self.mode_delta, self.ref_delta = [0] * 4, [0] * 4
        self.segment_probs = [255] * 3
        self.probabilities = copy.deepcopy(T["COEFF_PROBS"])

    def header(self):
        data = self.data
        tag = int.from_bytes(data[:3], "little")
        if tag & 1 or data[3:6] != b"\x9d\x01\x2a":
            raise ValueError("Unsupported VP8 frame")
        first_size = tag >> 5
        self.width = int.from_bytes(data[6:8], "little") & 0x3FFF
        self.height = int.from_bytes(data[8:10], "little") & 0x3FFF
        if not self.width or not self.height:
            raise ValueError("Invalid VP8 dimensions")
        self.mbw, self.mbh = (self.width + 15) // 16, (self.height + 15) // 16
        self.cw, self.ch = (self.width + 1) // 2, (self.height + 1) // 2
        self.y, self.u, self.v = [0] * (self.width * self.height), [0] * (self.cw * self.ch), [0] * (self.cw * self.ch)
        self.top = [MacroBlock() for _ in range(self.mbw)]
        self.top_border, self.left_border = [127] * (self.width + 20), [129] * 17
        b = self.b = BoolReader(data[10:10 + first_size])
        if b.literal(1) != 0:
            raise ValueError("Invalid VP8 color space")
        b.literal(1)
        self.segment_enabled = b.boolean()
        self.segment_map = False
        if self.segment_enabled:
            self.segment_map = b.boolean()
            if b.boolean():
                delta = not b.boolean()
                for segment in self.segments:
                    segment.delta = delta
                for segment in self.segments:
                    segment.quantizer = b.signed(7) if b.boolean() else 0
                for segment in self.segments:
                    segment.filter = b.signed(6) if b.boolean() else 0
            if self.segment_map:
                self.segment_probs = [b.literal(8) if b.boolean() else 255 for _ in range(3)]
        self.simple_filter, self.filter_level, self.sharpness = b.boolean(), b.literal(6), b.literal(3)
        if b.boolean() and b.boolean():
            self.ref_delta = [b.signed(6) if b.boolean() else 0 for _ in range(4)]
            self.mode_delta = [b.signed(6) if b.boolean() else 0 for _ in range(4)]
        count = 1 << b.literal(2)
        position = 10 + first_size
        sizes = [int.from_bytes(data[position + i * 3:position + i * 3 + 3], "little") for i in range(count - 1)]
        position += (count - 1) * 3
        self.partitions = []
        for size in [*sizes, len(data) - position - sum(sizes)]:
            self.partitions.append(BoolReader(data[position:position + size]))
            position += size
        yac = b.literal(7)
        ydc, y2dc, y2ac, uvdc, uvac = [b.signed(4) if b.boolean() else 0 for _ in range(5)]
        for segment in self.segments[:4 if self.segment_enabled else 1]:
            base = segment.quantizer + (yac if segment.delta else 0)
            segment.ydc, segment.yac = T["DC_QUANT"][clamp(base + ydc, 0, 127)], T["AC_QUANT"][clamp(base, 0, 127)]
            segment.y2dc = T["DC_QUANT"][clamp(base + y2dc, 0, 127)] * 2
            segment.y2ac = max(8, T["AC_QUANT"][clamp(base + y2ac, 0, 127)] * 155 // 100)
            segment.uvdc = min(132, T["DC_QUANT"][clamp(base + uvdc, 0, 127)])
            segment.uvac = T["AC_QUANT"][clamp(base + uvac, 0, 127)]
        b.literal(1)
        for i, plane in enumerate(T["COEFF_UPDATE_PROBS"]):
            for j, band in enumerate(plane):
                for k, context in enumerate(band):
                    for t, probability in enumerate(context):
                        if b.boolean(probability):
                            self.probabilities[i][j][k][t] = b.literal(8)
        self.skip_probability = b.literal(8) if b.boolean() else None

    def macroblock(self, x):
        b, mb = self.b, MacroBlock()
        if self.segment_enabled and self.segment_map:
            mb.segment = b.tree(T["SEGMENT_ID_TREE"], self.segment_probs)
        mb.skipped = b.boolean(self.skip_probability) if self.skip_probability is not None else False
        mb.luma = b.tree(T["KEYFRAME_YMODE_TREE"], T["KEYFRAME_YMODE_PROBS"])
        if mb.luma == 4:
            for y in range(4):
                for sx in range(4):
                    top, left = self.top[x].bpred[12 + sx], self.left.bpred[y]
                    mode = b.tree(T["KEYFRAME_BPRED_MODE_TREE"], T["KEYFRAME_BPRED_MODE_PROBS"][top][left])
                    mb.bpred[sx + y * 4] = mode
                    self.top[x].bpred[12 + sx] = self.left.bpred[y] = mode
        else:
            mode = [0, 2, 3, 1][mb.luma]
            for i in range(4):
                mb.bpred[12 + i] = self.left.bpred[i] = mode
        mb.chroma = b.tree(T["KEYFRAME_UV_MODE_TREE"], T["KEYFRAME_UV_MODE_PROBS"])
        self.top[x].luma, self.top[x].chroma = mb.luma, mb.chroma
        self.top[x].bpred = mb.bpred.copy()
        return mb

    def coefficients(self, block, partition, plane, complexity, dc, ac):
        b, skip, found = self.partitions[partition], False, False
        for index in range(1 if plane == 0 else 0, 16):
            probabilities = self.probabilities[plane][T["COEFF_BANDS"][index]][complexity]
            token = b.tree(T["DCT_TOKEN_TREE"], probabilities, 2 if skip else 0)
            if token == 11:
                break
            if token == 0:
                skip, found, complexity = True, True, 0
                continue
            if token <= 4:
                value = token
            else:
                extra = 0
                for probability in T["PROB_DCT_CAT"][token - 5]:
                    if not probability:
                        break
                    extra = extra * 2 + b.boolean(probability)
                value = T["DCT_CAT_BASE"][token - 5] + extra
            skip = False
            complexity = 1 if value == 1 else 2
            if b.boolean():
                value = -value
            position = T["ZIGZAG"][index]
            block[position] = value * (ac if position else dc)
            found = True
        return int(found)

    def residual(self, mb, x, partition):
        blocks, top, left = [[0] * 16 for _ in range(24)], self.top[x].complexity, self.left.complexity
        segment = self.segments[mb.segment]
        plane = 3 if mb.luma == 4 else 1
        if plane == 1:
            block = [0] * 16
            nonzero = self.coefficients(block, partition, 1, top[0] + left[0], segment.y2dc, segment.y2ac)
            top[0] = left[0] = nonzero
            iwht(block)
            for index in range(16):
                blocks[index][0] = block[index]
            plane = 0
        for y in range(4):
            previous = left[y + 1]
            for sx in range(4):
                block = blocks[sx + y * 4]
                nonzero = self.coefficients(block, partition, plane, top[sx + 1] + previous, segment.ydc, segment.yac)
                if block[0] or nonzero:
                    idct(block)
                previous = top[sx + 1] = nonzero
            left[y + 1] = previous
        for base in (5, 7):
            for y in range(2):
                previous = left[y + base]
                for sx in range(2):
                    block = blocks[sx + y * 2 + (16 if base == 5 else 20)]
                    nonzero = self.coefficients(block, partition, 2, top[sx + base] + previous, segment.uvdc, segment.uvac)
                    if block[0] or nonzero:
                        idct(block)
                    previous = top[sx + base] = nonzero
                left[y + base] = previous
        return blocks

    def predict_luma(self, x, y, mb, blocks):
        stride = 21
        workspace = [0] * 357
        if y == 0:
            workspace[1:21] = [127] * 20
        else:
            workspace[1:17] = self.top_border[x * 16:x * 16 + 16]
            workspace[17:21] = (
                [self.top_border[x * 16 + 15]] * 4
                if x == self.mbw - 1
                else self.top_border[x * 16 + 16:x * 16 + 20]
            )
        for offset in range(17, 21):
            for row in (4, 8, 12):
                workspace[row * stride + offset] = workspace[offset]
        for row in range(16):
            workspace[(row + 1) * stride] = 129 if x == 0 else self.left_border[row + 1]
        workspace[0] = 127 if y == 0 else 129 if x == 0 else self.left_border[0]
        if mb.luma != 4:
            predict(workspace, 16, 1, 1, stride, mb.luma, y != 0, x != 0)
        for sy in range(4):
            for sx in range(4):
                index = sx + sy * 4
                x0, y0 = sx * 4 + 1, sy * 4 + 1
                if mb.luma == 4:
                    predict_small(workspace, x0, y0, stride, mb.bpred[index])
                add_residue(workspace, blocks[index], x0, y0, stride)
        self.left_border[0] = workspace[16]
        for index in range(16):
            self.top_border[x * 16 + index] = workspace[16 * stride + 1 + index]
            self.left_border[index + 1] = workspace[(index + 1) * stride + 16]
        for sy in range(min(self.height - y * 16, 16)):
            for sx in range(min(self.width - x * 16, 16)):
                self.y[(y * 16 + sy) * self.width + x * 16 + sx] = workspace[(sy + 1) * stride + sx + 1]

    def predict_chroma(self, x, y, mb, blocks):
        width, height, stride = self.cw, self.ch, 9
        ylength, xlength = min(height - y * 8, 8), min(width - x * 8, 8)
        for plane, block_offset in ((self.u, 16), (self.v, 20)):
            workspace = [0] * 81
            for sy in range(8):
                workspace[(sy + 1) * stride] = (
                    129 if x == 0 or sy >= ylength else plane[(y * 8 + sy) * width + (x - 1) * 8 + 7]
                )
            for sx in range(8):
                workspace[sx + 1] = (
                    127 if y == 0 or sx >= xlength else plane[((y - 1) * 8 + 7) * width + x * 8 + sx]
                )
            if y == 0:
                workspace[0] = 127
            elif x == 0:
                workspace[0] = 129
            else:
                position = ((y - 1) * 8 + 7) * width + (x - 1) * 8 + 7
                workspace[0] = plane[position] if position < len(plane) else 127
            predict(workspace, 8, 1, 1, stride, mb.chroma, y != 0, x != 0)
            for sy in range(2):
                for sx in range(2):
                    add_residue(workspace, blocks[block_offset + sx + sy * 2], sx * 4 + 1, sy * 4 + 1, stride)
            for sy in range(ylength):
                for sx in range(xlength):
                    plane[(y * 8 + sy) * width + x * 8 + sx] = workspace[(sy + 1) * stride + sx + 1]

    def filter_parameters(self, mb):
        segment = self.segments[mb.segment]
        level = self.filter_level
        if self.segment_enabled:
            level = level + segment.filter if segment.delta else segment.filter
        level = clamp(level, 0, 63)
        if mb.luma == 4:
            level += self.mode_delta[0]
        level = clamp(level, 0, 63)
        interior = level
        if self.sharpness:
            interior >>= 2 if self.sharpness > 4 else 1
            interior = min(interior, 9 - self.sharpness)
        return level, max(1, interior), 2 if level >= 40 else 1

    def loop_filter(self, x, y, mb):
        level, interior, hev = self.filter_parameters(mb)
        if not level:
            return
        macro_limit, sub_limit = (level + 2) * 2 + interior, level * 2 + interior
        luma_x, luma_y = min(16, self.width - x * 16), min(16, self.height - y * 16)
        chroma_x, chroma_y = min(8, self.cw - x * 8), min(8, self.ch - y * 8)
        for axis in (0, 1):
            along, across = (luma_y, luma_x) if axis == 0 else (luma_x, luma_y)
            calong, cacross = (chroma_y, chroma_x) if axis == 0 else (chroma_x, chroma_y)
            stride = 1 if axis == 0 else self.width
            cstride = 1 if axis == 0 else self.cw

            def point(distance, offset, chroma=False):
                size, width = (8, self.cw) if chroma else (16, self.width)
                sx, sy = (offset, distance) if axis else (distance, offset)
                return (y * size + sy) * width + x * size + sx

            if (x if axis == 0 else y) > 0:
                if across >= (2 if self.simple_filter else 4):
                    for offset in range(along):
                        filter_edge(self.y, point(0, offset), stride, macro_limit, interior, hev, "simple" if self.simple_filter else "macro")
                if not self.simple_filter and cacross >= 4:
                    for offset in range(calong):
                        for plane in (self.u, self.v):
                            filter_edge(plane, point(0, offset, True), cstride, macro_limit, interior, hev, "macro")
            if mb.luma == 4 or not mb.skipped:
                margin = 1 if self.simple_filter else 3
                for distance in range(4, across - margin, 4):
                    for offset in range(along):
                        filter_edge(self.y, point(distance, offset), stride, sub_limit, interior, hev, "simple" if self.simple_filter else "sub")
                if not self.simple_filter and cacross == 8:
                    for offset in range(calong):
                        for plane in (self.u, self.v):
                            filter_edge(plane, point(4, offset, True), cstride, sub_limit, interior, hev, "sub")

    def decode(self):
        self.header()
        macroblocks = []
        for y in range(self.mbh):
            self.left = MacroBlock()
            for x in range(self.mbw):
                mb = self.macroblock(x)
                if mb.skipped:
                    start = 1 if mb.luma == 4 else 0
                    for index in range(start, 9):
                        self.left.complexity[index] = self.top[x].complexity[index] = 0
                    blocks = [[0] * 16 for _ in range(24)]
                else:
                    blocks = self.residual(mb, x, y % len(self.partitions))
                self.predict_luma(x, y, mb, blocks)
                self.predict_chroma(x, y, mb, blocks)
                macroblocks.append(mb)
            self.left_border = [129] * 17
        for y in range(self.mbh):
            for x in range(self.mbw):
                self.loop_filter(x, y, macroblocks[y * self.mbw + x])
        y = np.asarray(self.y, dtype=np.int32).reshape(self.height, self.width) - 16
        u = np.asarray(self.u, dtype=np.int32).reshape(self.ch, self.cw).repeat(2, axis=0).repeat(2, axis=1)[:self.height, :self.width] - 128
        v = np.asarray(self.v, dtype=np.int32).reshape(self.ch, self.cw).repeat(2, axis=0).repeat(2, axis=1)[:self.height, :self.width] - 128
        r, g, b = (298 * y + 409 * v + 128) >> 8, (298 * y - 100 * u - 208 * v + 128) >> 8, (298 * y + 516 * u + 128) >> 8
        rgba = np.empty((self.height, self.width, 4), dtype=np.uint8)
        rgba[..., :3] = np.clip(np.stack((r, g, b), axis=2), 0, 255)
        rgba[..., 3] = 255
        return rgba.tobytes(), self.width, self.height


def add_residue(workspace, block, x0, y0, stride):
    for y in range(4):
        for x in range(4):
            position = (y0 + y) * stride + x0 + x
            workspace[position] = clamp(workspace[position] + block[y * 4 + x])


def predict(a, size, x0, y0, stride, mode, above=True, left=True):
    if mode == 0:
        shift = 2 if size == 8 else 3
        total = 0
        if left:
            total += sum(a[(y + 1) * stride] for y in range(size))
            shift += 1
        if above:
            total += sum(a[x + 1] for x in range(size))
            shift += 1
        value = 128 if not left and not above else (total + (1 << (shift - 1))) >> shift
    for y in range(size):
        for x in range(size):
            position = (y0 + y) * stride + x0 + x
            if mode == 0:
                a[position] = value
            elif mode == 1:
                a[position] = a[(y0 + y - 1) * stride + x0 + x]
            elif mode == 2:
                a[position] = a[(y0 + y) * stride + x0 + x - 1]
            elif mode == 3:
                a[position] = clamp(a[(y0 + y) * stride + x0 - 1] + a[(y0 - 1) * stride + x0 + x] - a[(y0 - 1) * stride + x0 - 1])


def avg2(a, b):
    return (a + b + 1) >> 1


def avg3(a, b, c):
    return (a + 2 * b + c + 2) >> 2


def predict_small(a, x0, y0, stride, mode):
    top = a[(y0 - 1) * stride + x0:(y0 - 1) * stride + x0 + 8]
    left = [a[(y0 + i) * stride + x0 - 1] for i in range(4)]
    corner = a[(y0 - 1) * stride + x0 - 1]
    edges = left[::-1] + [corner] + top[:4]
    if mode == 1:
        predict(a, 4, x0, y0, stride, 3)
    elif mode == 0:
        value = (sum(left) + sum(top[:4]) + 4) >> 3
        for y in range(4):
            for x in range(4):
                a[(y0 + y) * stride + x0 + x] = value
    elif mode == 2:
        values = [avg3(*([corner] + top)[i:i + 3]) for i in range(4)]
        for y in range(4):
            a[(y0 + y) * stride + x0:(y0 + y) * stride + x0 + 4] = values
    elif mode == 3:
        source = [corner] + left + [left[-1]]
        for y in range(4):
            a[(y0 + y) * stride + x0:(y0 + y) * stride + x0 + 4] = [avg3(*source[y:y + 3])] * 4
    elif mode in {4, 5}:
        source = top + [top[-1]] if mode == 4 else edges
        values = [avg3(*source[i:i + 3]) for i in range(7)]
        for y in range(4):
            start = y if mode == 4 else 3 - y
            a[(y0 + y) * stride + x0:(y0 + y) * stride + x0 + 4] = values[start:start + 4]
    else:
        arguments = {**{f"e{i}": value for i, value in enumerate(edges)}, **{f"a{i}": value for i, value in enumerate(top)}, **{f"l{i}": value for i, value in enumerate(left)}}
        for y, x, operation, names in T["BPRED_RULES"][str(mode)]:
            values = [arguments[name] for name in names]
            value = avg2(*values) if operation == 2 else avg3(*values) if operation == 3 else values[0]
            a[(y0 + y) * stride + x0 + x] = value


def filter_edge(pixels, point, stride, limit, interior, hev, kind):
    def at(offset):
        return pixels[point + offset * stride]

    if 2 * abs(at(-1) - at(0)) + abs(at(-2) - at(1)) // 2 > limit:
        return
    if kind != "simple" and any(
        abs(at(a) - at(b)) > interior
        for a, b in ((-4, -3), (-3, -2), (-2, -1), (3, 2), (2, 1), (1, 0))
    ):
        return
    high = abs(at(-2) - at(-1)) > hev or abs(at(1) - at(0)) > hev

    def signed(value):
        return clamp(value, -128, 127)

    def put(offset, value):
        pixels[point + offset * stride] = signed(value) + 128

    if kind == "macro" and not high:
        values = [at(offset) - 128 for offset in range(-4, 4)]
        weight = signed(signed(values[2] - values[5]) + 3 * (values[4] - values[3]))
        for index, factor in enumerate((27, 18, 9)):
            adjustment = signed((factor * weight + 63) >> 7)
            put(index, values[4 + index] - adjustment)
            put(-1 - index, values[3 - index] + adjustment)
        return
    p1, p0, q0, q1 = (at(offset) - 128 for offset in (-2, -1, 0, 1))
    outer = signed(p1 - q1) if kind != "sub" or high else 0
    adjustment = signed(outer + 3 * (q0 - p0))
    b, a = signed(adjustment + 3) >> 3, signed(adjustment + 4) >> 3
    put(0, q0 - a)
    put(-1, p0 + b)
    if kind == "sub" and not high:
        amount = (a + 1) >> 1
        put(1, q1 - amount)
        # Preserve image-rs 0.24.8's subtraction at the p1 tap.
        put(-2, p1 - amount)
