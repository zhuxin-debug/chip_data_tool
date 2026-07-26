from __future__ import annotations

import re
from dataclasses import dataclass

from .bit_vector import BitVector
from .errors import ParseError
from .parser import parse_value


PATTERN_RE = re.compile(
    r"^(?:(?P<width>\d+)'(?P<base>[hb])|0(?P<prefix_base>[xb]))"
    r"(?P<digits>[0-9a-fxz?_]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PatternVector:
    value: int
    care_mask: int
    width: int


@dataclass(frozen=True, slots=True)
class BitComparison:
    bit: int
    actual: int
    expected: str
    status: str


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    actual: BitVector
    expected: PatternVector
    diff_mask: int
    bits: tuple[BitComparison, ...]

    @property
    def matches(self) -> bool:
        return self.diff_mask == 0

    @property
    def different_count(self) -> int:
        return self.diff_mask.bit_count()

    @property
    def ignored_count(self) -> int:
        return self.actual.width - self.expected.care_mask.bit_count()

    @property
    def first_difference_msb(self) -> int | None:
        return self.diff_mask.bit_length() - 1 if self.diff_mask else None


def parse_expected_pattern(text: str, width: int | None = None) -> PatternVector:
    clean = text.strip().replace("_", "").replace(" ", "")
    match = PATTERN_RE.fullmatch(clean)
    if match and any(char in match.group("digits").lower() for char in "xz?"):
        base_code = (match.group("base") or match.group("prefix_base")).lower()
        bits_per_digit = 4 if base_code == "h" or base_code == "x" else 1
        base = 16 if bits_per_digit == 4 else 2
        digits = match.group("digits")
        declared_width = int(match.group("width")) if match.group("width") else None
        encoded_width = len(digits) * bits_per_digit
        final_width = width or declared_width or encoded_width
        if declared_width is not None and width is not None and declared_width != width:
            raise ParseError(f"Expected 声明为 {declared_width} bit，但 Actual 为 {width} bit")
        if encoded_width > final_width:
            raise ParseError(f"Expected 数字至少需要 {encoded_width} bit，超过目标 {final_width} bit")

        value = 0
        care_mask = 0
        digit_mask = (1 << bits_per_digit) - 1
        for digit in digits:
            value <<= bits_per_digit
            care_mask <<= bits_per_digit
            if digit.lower() not in "xz?":
                try:
                    value |= int(digit, base)
                except ValueError as exc:
                    raise ParseError(f"Expected 包含非法字符：{digit}") from exc
                care_mask |= digit_mask
        if final_width > encoded_width:
            high_width = final_width - encoded_width
            care_mask |= ((1 << high_width) - 1) << encoded_width
        return PatternVector(value, care_mask, final_width)

    parsed = parse_value(clean, width=width)
    return PatternVector(parsed.vector.value, parsed.vector.mask, parsed.vector.width)


def compare_actual_expected(actual: BitVector, expected_text: str) -> ComparisonResult:
    expected = parse_expected_pattern(expected_text, actual.width)
    diff_mask = (actual.value ^ expected.value) & expected.care_mask
    bits: list[BitComparison] = []
    for bit in range(actual.width - 1, -1, -1):
        actual_bit = (actual.value >> bit) & 1
        if not ((expected.care_mask >> bit) & 1):
            expected_bit = "X"
            status = "忽略"
        else:
            expected_bit = str((expected.value >> bit) & 1)
            status = "不同" if (diff_mask >> bit) & 1 else "相同"
        bits.append(BitComparison(bit, actual_bit, expected_bit, status))
    return ComparisonResult(actual, expected, diff_mask, tuple(bits))
