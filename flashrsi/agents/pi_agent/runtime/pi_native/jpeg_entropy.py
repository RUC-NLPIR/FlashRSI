"""Huffman JPEG entropy decoding without an external image decoder.

Return the original quantized DCT coefficients in natural 8 by 8 order. The
separate Photon image port owns dequantization, IDCT and color conversion.
Supports sequential and progressive DCT scans, sampling and restart markers
as specified in ITU-T T.81, sections F and G. NumPy only stores the coefficients.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_ZIGZAG = (
    0,
    1,
    8,
    16,
    9,
    2,
    3,
    10,
    17,
    24,
    32,
    25,
    18,
    11,
    4,
    5,
    12,
    19,
    26,
    33,
    40,
    48,
    41,
    34,
    27,
    20,
    13,
    6,
    7,
    14,
    21,
    28,
    35,
    42,
    49,
    56,
    57,
    50,
    43,
    36,
    29,
    22,
    15,
    23,
    30,
    37,
    44,
    51,
    58,
    59,
    52,
    45,
    38,
    31,
    39,
    46,
    53,
    60,
    61,
    54,
    47,
    55,
    62,
    63,
)


@dataclass
class JpegImage:
    width: int
    height: int
    coefficients: list[np.ndarray]
    quantization: list[np.ndarray]
    quant_tbl_no: list[int]
    sampling: list[tuple[int, int]]
    color: str


@dataclass
class _Component:
    identifier: int
    horizontal: int
    vertical: int
    quantization: int
    columns: int = 0
    rows: int = 0
    coefficients: np.ndarray | None = None


class _Bits:
    __slots__ = ("data", "position", "byte", "remaining")

    def __init__(self, data: bytes, position: int):
        self.data = data
        self.position = position
        self.byte = 0
        self.remaining = 0

    def _fill(self):
        if self.position >= len(self.data):
            raise ValueError("Truncated JPEG entropy data")
        value = self.data[self.position]
        self.position += 1
        if value == 255:
            if self.position >= len(self.data):
                raise ValueError("Truncated JPEG byte stuffing")
            if self.data[self.position] != 0:
                raise ValueError("Unexpected JPEG marker inside entropy data")
            self.position += 1
        self.byte, self.remaining = value, 8

    def bit(self):
        if not self.remaining:
            self._fill()
        self.remaining -= 1
        return (self.byte >> self.remaining) & 1

    def read(self, count):
        result = 0
        while count:
            if not self.remaining:
                self._fill()
            take = min(count, self.remaining)
            self.remaining -= take
            result = (result << take) | (
                (self.byte >> self.remaining) & ((1 << take) - 1)
            )
            count -= take
        return result

    def extend(self, count):
        if count == 0:
            return 0
        value = self.read(count)
        return value if value >= 1 << (count - 1) else value + 1 - (1 << count)

    def restart(self, expected):
        self.remaining = 0
        marker, self.position = _marker(self.data, self.position)
        if marker != 0xD0 + expected:
            raise ValueError(f"JPEG restart marker RST{expected} was expected")


class _Huffman:
    __slots__ = ("minimum", "maximum", "offset", "values")

    def __init__(self, counts, values):
        if sum(counts) != len(values):
            raise ValueError("Truncated JPEG Huffman table")
        self.minimum = [0] * 17
        self.maximum = [-1] * 17
        self.offset = [0] * 17
        self.values = values
        code = index = 0
        for length, count in enumerate(counts, 1):
            if code + count > 1 << length:
                raise ValueError("Oversubscribed JPEG Huffman table")
            if count:
                self.minimum[length] = code
                self.maximum[length] = code + count - 1
                self.offset[length] = index - code
            code = (code + count) << 1
            index += count

    def decode(self, bits):
        code = 0
        for length in range(1, 17):
            code = (code << 1) | bits.bit()
            if self.minimum[length] <= code <= self.maximum[length]:
                return self.values[code + self.offset[length]]
        raise ValueError("Invalid JPEG Huffman code")


def _marker(data, position):
    if position >= len(data) or data[position] != 255:
        raise ValueError("JPEG marker was expected")
    while position < len(data) and data[position] == 255:
        position += 1
    if position >= len(data) or data[position] == 0:
        raise ValueError("Truncated or invalid JPEG marker")
    return data[position], position + 1


def _word(data, position):
    if position + 2 > len(data):
        raise ValueError("Truncated JPEG segment")
    return (data[position] << 8) | data[position + 1]


def _signed16(value):
    return ((value + 32768) & 65535) - 32768


def _first_block(block, bits, dc, ac, start, end, low, predictor, eob_run):
    if start == 0:
        if dc is None:
            raise ValueError("JPEG scan uses an undefined DC Huffman table")
        size = dc.decode(bits)
        if size > 11:
            raise ValueError("Invalid JPEG DC magnitude category")
        predictor = _signed16(predictor + bits.extend(size))
        block[0] = _signed16(predictor << low)
    index = max(start, 1)
    if index <= end and eob_run:
        return predictor, eob_run - 1
    while index <= end:
        if ac is None:
            raise ValueError("JPEG scan uses an undefined AC Huffman table")
        value = ac.decode(bits)
        run, size = value >> 4, value & 15
        if size:
            index += run
            if index > end:
                raise ValueError("JPEG AC coefficient exceeds spectral selection")
            block[_ZIGZAG[index]] = _signed16(bits.extend(size) << low)
            index += 1
        elif run == 15:
            index += 16
        else:
            eob_run = (1 << run) - 1 + bits.read(run)
            break
    return predictor, eob_run


def _refine_nonzero(block, bits, start, end, zeroes, bit):
    for index in range(start, end + 1):
        position = _ZIGZAG[index]
        value = int(block[position])
        if value == 0:
            if zeroes == 0:
                return index
            zeroes -= 1
        elif bits.bit() and not value & bit:
            value += bit if value > 0 else -bit
            if not -32768 <= value <= 32767:
                raise ValueError("JPEG coefficient overflow")
            block[position] = value
    return end + 1


def _refine_block(block, bits, ac, start, end, low, eob_run):
    bit = 1 << low
    if start == 0:
        if bits.bit():
            block[0] = int(block[0]) | bit
        return eob_run
    if eob_run:
        _refine_nonzero(block, bits, start, end, 64, bit)
        return eob_run - 1
    index = start
    while index <= end:
        if ac is None:
            raise ValueError("JPEG scan uses an undefined AC Huffman table")
        symbol = ac.decode(bits)
        zeroes, size = symbol >> 4, symbol & 15
        value = 0
        if size == 0:
            if zeroes != 15:
                eob_run = (1 << zeroes) - 1 + bits.read(zeroes)
                _refine_nonzero(block, bits, index, end, 64, bit)
                break
        elif size == 1:
            value = bit if bits.bit() else -bit
        else:
            raise ValueError("Invalid progressive JPEG AC refinement symbol")
        index = _refine_nonzero(block, bits, index, end, zeroes, bit)
        if value:
            if index > end:
                raise ValueError("JPEG refinement coefficient exceeds scan")
            block[_ZIGZAG[index]] = value
        index += 1
    return eob_run


def _scan(data, position, header, components, huffman, interval, mcus, progressive):
    if not header:
        raise ValueError("Empty JPEG scan header")
    count = header[0]
    if not 1 <= count <= len(components) or len(header) != 4 + 2 * count:
        raise ValueError("Invalid JPEG scan component count")
    selected = []
    identifiers = set()
    for index in range(count):
        identifier, tables = header[1 + 2 * index : 3 + 2 * index]
        component = next((c for c in components if c.identifier == identifier), None)
        if component is None or identifier in identifiers:
            raise ValueError("Unknown or repeated JPEG scan component")
        identifiers.add(identifier)
        selected.append(
            (component, huffman.get((0, tables >> 4)), huffman.get((1, tables & 15)))
        )
    start, end, approximation = header[-3:]
    high, low = approximation >> 4, approximation & 15
    if not (0 <= start <= end <= 63 and high <= 13 and low <= 13):
        raise ValueError("Invalid JPEG spectral selection")
    if progressive:
        if (start == 0 and end != 0) or (start > 0 and count != 1):
            raise ValueError("Invalid progressive JPEG spectral selection")
        if high and high != low + 1:
            raise ValueError("Invalid progressive JPEG successive approximation")
    elif (start, end, high, low) != (0, 63, 0, 0):
        raise ValueError("Invalid sequential JPEG spectral selection")
    interleaved = count > 1
    columns, rows = (
        mcus if interleaved else (selected[0][0].columns, selected[0][0].rows)
    )
    bits = _Bits(data, position)
    predictors = [0] * count
    eob_run = 0
    restart_number = 0
    for mcu in range(columns * rows):
        if interval and mcu and mcu % interval == 0:
            bits.restart(restart_number)
            restart_number = (restart_number + 1) & 7
            predictors = [0] * count
            eob_run = 0
        mcu_y, mcu_x = divmod(mcu, columns)
        for index, (component, dc, ac) in enumerate(selected):
            vertical, horizontal = (
                (component.vertical, component.horizontal) if interleaved else (1, 1)
            )
            for y in range(vertical):
                for x in range(horizontal):
                    block = component.coefficients[
                        mcu_y * vertical + y, mcu_x * horizontal + x
                    ].reshape(64)
                    if high:
                        eob_run = _refine_block(
                            block, bits, ac, start, end, low, eob_run
                        )
                    else:
                        predictors[index], eob_run = _first_block(
                            block,
                            bits,
                            dc,
                            ac,
                            start,
                            end,
                            low,
                            predictors[index],
                            eob_run,
                        )
    return bits.position


def parse_jpeg(data: bytes) -> JpegImage:
    """Decode sequential/progressive Huffman JPEG to quantized coefficients.

    Component arrays have shape ``(block_rows, block_columns, 8, 8)`` and
    ``int16`` dtype. Quantization table slots retain their JPEG table IDs;
    sampling factors are ``(vertical, horizontal)`` as in libjpeg metadata.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("JPEG data must be bytes")
    data = bytes(data)
    if data[:2] != b"\xff\xd8":
        raise ValueError("JPEG SOI marker is missing")
    position, width, height, interval = 2, 0, 0, 0
    components, quantization, huffman = [], {}, {}
    progressive = jfif = False
    adobe = None
    mcus = (0, 0)
    scans = 0
    while position < len(data):
        marker, position = _marker(data, position)
        if marker == 0xD9:
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if marker == 0xD8:
            raise ValueError("Unexpected JPEG SOI marker")
        length = _word(data, position)
        if length < 2 or position + length > len(data):
            raise ValueError("Truncated JPEG segment")
        segment = data[position + 2 : position + length]
        position += length
        if marker == 0xDB:
            offset = 0
            while offset < len(segment):
                specification = segment[offset]
                offset += 1
                precision, number = specification >> 4, specification & 15
                if precision > 1 or number > 3:
                    raise ValueError("Invalid JPEG quantization table")
                size = 64 * (precision + 1)
                if offset + size > len(segment):
                    raise ValueError("Truncated JPEG quantization table")
                values = np.frombuffer(
                    segment[offset : offset + size],
                    dtype=">u2" if precision else np.uint8,
                )
                table = np.empty(64, dtype=np.uint16)
                table[list(_ZIGZAG)] = values
                quantization[number] = table.reshape(8, 8)
                offset += size
        elif marker == 0xC4:
            offset = 0
            while offset < len(segment):
                specification = segment[offset]
                if (
                    specification >> 4 > 1
                    or specification & 15 > 3
                    or offset + 17 > len(segment)
                ):
                    raise ValueError("Invalid JPEG Huffman table")
                counts = segment[offset + 1 : offset + 17]
                total = sum(counts)
                values = segment[offset + 17 : offset + 17 + total]
                huffman[(specification >> 4, specification & 15)] = _Huffman(
                    counts, values
                )
                offset += 17 + total
        elif marker in {0xC0, 0xC1, 0xC2}:
            if components or len(segment) < 6:
                raise ValueError("Invalid or repeated JPEG frame header")
            precision = segment[0]
            height, width = _word(segment, 1), _word(segment, 3)
            count = segment[5]
            if precision != 8 or not width or not height or count not in {1, 3, 4}:
                raise ValueError("Unsupported JPEG precision, dimensions or components")
            if len(segment) != 6 + 3 * count:
                raise ValueError("Truncated JPEG frame header")
            for index in range(count):
                identifier, factors, table = segment[6 + 3 * index : 9 + 3 * index]
                horizontal, vertical = factors >> 4, factors & 15
                if not (1 <= horizontal <= 4 and 1 <= vertical <= 4 and table <= 3):
                    raise ValueError("Invalid JPEG component sampling or table")
                if any(component.identifier == identifier for component in components):
                    raise ValueError("Repeated JPEG component identifier")
                components.append(_Component(identifier, horizontal, vertical, table))
            max_horizontal = max(component.horizontal for component in components)
            max_vertical = max(component.vertical for component in components)
            mcus = (
                (width + 8 * max_horizontal - 1) // (8 * max_horizontal),
                (height + 8 * max_vertical - 1) // (8 * max_vertical),
            )
            for component in components:
                component.columns = (
                    width * component.horizontal + 8 * max_horizontal - 1
                ) // (8 * max_horizontal)
                component.rows = (
                    height * component.vertical + 8 * max_vertical - 1
                ) // (8 * max_vertical)
                component.coefficients = np.zeros(
                    (
                        mcus[1] * component.vertical,
                        mcus[0] * component.horizontal,
                        8,
                        8,
                    ),
                    dtype=np.int16,
                )
            progressive = marker == 0xC2
        elif marker == 0xDA:
            if not components:
                raise ValueError("JPEG scan precedes frame header")
            if any(
                component.quantization not in quantization for component in components
            ):
                raise ValueError("JPEG scan uses an undefined quantization table")
            position = _scan(
                data,
                position,
                segment,
                components,
                huffman,
                interval,
                mcus,
                progressive,
            )
            scans += 1
        elif marker == 0xDD:
            if len(segment) != 2:
                raise ValueError("Invalid JPEG restart interval")
            interval = _word(segment, 0)
        elif marker == 0xE0 and segment.startswith(b"JFIF\x00"):
            jfif = True
        elif marker == 0xEE and segment.startswith(b"Adobe") and len(segment) >= 12:
            adobe = segment[11]
        elif marker in {
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
            0xCC,
        }:
            raise ValueError("Unsupported JPEG lossless or arithmetic coding")
    if not scans:
        raise ValueError("JPEG contains no image scans")
    if len(components) == 1:
        color = "JCS_GRAYSCALE"
    elif len(components) == 4:
        color = "JCS_YCCK" if adobe == 2 else "JCS_CMYK"
    elif adobe is not None:
        color = "JCS_RGB" if adobe == 0 else "JCS_YCbCr"
    elif jfif:
        color = "JCS_YCbCr"
    else:
        color = (
            "JCS_RGB"
            if [c.identifier for c in components] == [82, 71, 66]
            else "JCS_YCbCr"
        )
    tables = [
        quantization.get(index, np.zeros((8, 8), dtype=np.uint16))
        for index in range(max(quantization) + 1)
    ]
    return JpegImage(
        width=width,
        height=height,
        coefficients=[
            component.coefficients[: component.rows, : component.columns].copy()
            for component in components
        ],
        quantization=tables,
        quant_tbl_no=[component.quantization for component in components],
        sampling=[
            (component.vertical, component.horizontal) for component in components
        ],
        color=color,
    )
