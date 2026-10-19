from __future__ import annotations

import re
from dataclasses import dataclass

from .bit_vector import BitVector
from .errors import ParseError


SV_LITERAL_RE = re.compile(
    r"^(?P<prefix_sign>[+-]?)(?P<width>\d+)?'(?P<signed>s)?"
    r"(?P<base>[bodh])(?P<digits>[+-]?[0-9a-fxz?]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedValue:
    vector: BitVector
    detected_format: str


def _round_to_byte(bits: int) -> int:
    return max(8, ((bits + 7) // 8) * 8)


def _infer_decimal_width(value: int, signed: bool) -> int:
    if value < 0:
        bits = (~value).bit_length() + 1
    elif signed:
        bits = value.bit_length() + 1
    else:
        bits = max(1, value.bit_length())
    return _round_to_byte(bits)


def _validate_and_pack(
    value: int,
    width: int,
    signed: bool,
    *,
    numeric_signed_range: bool,
) -> BitVector:
    if width <= 0:
        raise ParseError("数据位宽必须大于 0")

    if value < 0:
        if not signed:
            raise ParseError("负数必须选择有符号数据")
        minimum = -(1 << (width - 1))
        maximum = (1 << (width - 1)) - 1
        if not minimum <= value <= maximum:
            raise ParseError(f"数值 {value} 超出 {width} bit 有符号范围 [{minimum}, {maximum}]")
        return BitVector(value & ((1 << width) - 1), width, True)

    maximum = (1 << width) - 1
    if value > maximum:
        raise ParseError(f"数值 0x{value:X} 超出 {width} bit 可表示范围")
    if signed and numeric_signed_range and value > (1 << (width - 1)) - 1:
        raise ParseError(f"十进制数值 {value} 超出 {width} bit 有符号正数范围")
    return BitVector(value, width, signed)


def _parse_byte_stream(text: str, width: int | None, signed: bool | None) -> ParsedValue:
    tokens = [token for token in re.split(r"[\s,:;-]+", text.strip()) if token]
    if not tokens:
        raise ParseError("请输入至少一个字节")

    value = 0
    for token in tokens:
        token = token[2:] if token.lower().startswith("0x") else token
        if not re.fullmatch(r"[0-9a-fA-F]{1,2}", token):
            raise ParseError(f"字节“{token}”格式错误，应为 00 到 FF")
        value = (value << 8) | int(token, 16)

    inferred_width = len(tokens) * 8
    final_width = width or inferred_width
    if final_width < inferred_width:
        raise ParseError(f"{len(tokens)} 个字节至少需要 {inferred_width} bit")
    return ParsedValue(
        _validate_and_pack(value, final_width, bool(signed), numeric_signed_range=False),
        "字节流",
    )


def parse_value(
    text: str,
    format_hint: str = "auto",
    width: int | None = None,
    signed: bool | None = None,
) -> ParsedValue:
    """Parse a user value into a fixed-width bit vector.

    ``format_hint`` accepts ``auto``, ``hex``, ``bin``, ``dec`` or ``bytes``.
    A width of ``None`` or ``0`` enables format-aware inference.
    """

    if not isinstance(text, str) or not text.strip():
        raise ParseError("请输入原始数据")
    if width == 0:
        width = None
    if width is not None and width <= 0:
        raise ParseError("数据位宽必须大于 0")

    hint = format_hint.lower()
    if hint not in {"auto", "hex", "bin", "dec", "bytes"}:
        raise ParseError(f"不支持的输入格式：{format_hint}")
    if hint == "bytes":
        return _parse_byte_stream(text, width, signed)

    # A pasted one-line log value may have a trailing SystemVerilog comment.
    clean = text.split("//", 1)[0].strip().replace("_", "").replace(" ", "")
    if "\n" in clean or "\r" in clean:
        raise ParseError("单条模式只能输入一个数据；多条数据请使用批量处理")

    sv_match = SV_LITERAL_RE.fullmatch(clean)
    if sv_match:
        groups = sv_match.groupdict()
        digits = groups["digits"]
        if any(char in digits.lower() for char in "xz?"):
            raise ParseError("第一版不接受包含 X、Z 或 ? 的四态数据")

        base_code = groups["base"].lower()
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[base_code]
        detected = {"b": "SystemVerilog 二进制", "o": "SystemVerilog 八进制", "d": "SystemVerilog 十进制", "h": "SystemVerilog 十六进制"}[base_code]
        combined_sign = groups["prefix_sign"]
        if digits.startswith(("+", "-")):
            if combined_sign:
                raise ParseError("数值中出现了重复符号")
            combined_sign, digits = digits[0], digits[1:]
        if combined_sign and base != 10:
            raise ParseError("负号只支持十进制数值；位模式请使用补码形式")
        try:
            value = int((combined_sign or "") + digits, base)
        except ValueError as exc:
            raise ParseError("SystemVerilog 数值格式错误") from exc

        declared_width = int(groups["width"]) if groups["width"] else None
        if declared_width is not None and declared_width <= 0:
            raise ParseError("声明位宽必须大于 0")
        if width is not None and declared_width is not None and width != declared_width:
            raise ParseError(f"输入声明为 {declared_width} bit，但界面指定为 {width} bit")
        literal_signed = bool(groups["signed"]) or value < 0
        final_signed = literal_signed if signed is None else signed
        if value < 0 and not final_signed:
            raise ParseError("负数不能按无符号数据解析")

        if declared_width:
            inferred_width = declared_width
        elif base == 10:
            inferred_width = _infer_decimal_width(value, final_signed)
        else:
            bits_per_digit = {2: 1, 8: 3, 16: 4}[base]
            inferred_width = max(1, len(digits) * bits_per_digit)
        final_width = width or inferred_width
        return ParsedValue(
            _validate_and_pack(
                value,
                final_width,
                final_signed,
                numeric_signed_range=(base == 10),
            ),
            detected,
        )

    lowered = clean.lower()
    detected: str
    base: int
    digits: str
    if hint == "hex" or (hint == "auto" and lowered.startswith("0x")):
        base, detected = 16, "十六进制"
        digits = clean[2:] if lowered.startswith("0x") else clean
    elif hint == "bin" or (hint == "auto" and lowered.startswith("0b")):
        base, detected = 2, "二进制"
        digits = clean[2:] if lowered.startswith("0b") else clean
    elif hint == "auto" and re.search(r"[a-f]", lowered):
        base, detected, digits = 16, "十六进制", clean
    elif hint == "dec" or hint == "auto":
        base, detected, digits = 10, "十进制", clean
    else:
        raise ParseError(f"无法按 {format_hint} 格式识别输入")

    if not digits:
        raise ParseError("数值内容为空")
    valid_patterns = {2: r"[01]+", 10: r"[+-]?\d+", 16: r"[0-9a-fA-F]+"}
    if not re.fullmatch(valid_patterns[base], digits):
        names = {2: "二进制", 10: "十进制", 16: "十六进制"}
        raise ParseError(f"输入包含非法的{names[base]}字符")

    value = int(digits, base)
    inferred_signed = value < 0
    final_signed = inferred_signed if signed is None else signed
    if value < 0 and not final_signed:
        raise ParseError("负数不能按无符号数据解析")

    if base == 16:
        inferred_width = max(1, len(digits) * 4)
    elif base == 2:
        inferred_width = max(1, len(digits))
    else:
        inferred_width = _infer_decimal_width(value, final_signed)
    final_width = width or inferred_width
    return ParsedValue(
        _validate_and_pack(
            value,
            final_width,
            final_signed,
            numeric_signed_range=(base == 10),
        ),
        detected,
    )
