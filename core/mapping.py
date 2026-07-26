from __future__ import annotations

import re
from dataclasses import dataclass

from .bit_vector import BitVector
from .errors import MappingError, ParseError
from .parser import parse_value


LHS_RE = re.compile(r"^output\[(?P<msb>\d+)(?::(?P<lsb>\d+))?\]$", re.IGNORECASE)
RHS_INPUT_RE = re.compile(r"^input\[(?P<msb>\d+)(?::(?P<lsb>\d+))?\]$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MappingRow:
    output_range: str
    source: str
    width: int
    value: str


@dataclass(frozen=True, slots=True)
class MappingBit:
    output_bit: int
    expression: str
    value: int


@dataclass(frozen=True, slots=True)
class MappingResult:
    vector: BitVector
    rows: tuple[MappingRow, ...]
    bits: tuple[MappingBit, ...]


def _parse_range(match: re.Match[str], name: str) -> tuple[int, int, int]:
    msb = int(match.group("msb"))
    lsb = int(match.group("lsb")) if match.group("lsb") is not None else msb
    if msb < lsb:
        raise MappingError(f"{name}[{msb}:{lsb}] 范围方向错误，应为 MSB:LSB")
    return msb, lsb, msb - lsb + 1


def _missing_ranges(mask: int, width: int) -> str:
    missing = [bit for bit in range(width) if not (mask >> bit) & 1]
    ranges: list[str] = []
    start = previous = missing[0]
    for bit in missing[1:]:
        if bit == previous + 1:
            previous = bit
            continue
        ranges.append(f"[{previous}:{start}]" if previous != start else f"[{start}]")
        start = previous = bit
    ranges.append(f"[{previous}:{start}]" if previous != start else f"[{start}]")
    return ", ".join(reversed(ranges))


def _input_slice(source: BitVector, expression: str) -> BitVector | None:
    match = RHS_INPUT_RE.fullmatch(expression.strip())
    if not match:
        return None
    input_msb, input_lsb, _ = _parse_range(match, "input")
    if input_msb >= source.width:
        raise MappingError(f"{expression} 超出输入范围 [{source.width - 1}:0]")
    return source.slice(input_msb, input_lsb)


def _resolve_term(source: BitVector, term: str, context_width: int) -> BitVector:
    text = term.strip()
    input_vector = _input_slice(source, text)
    if input_vector is not None:
        vector = input_vector
    elif text in {"'0", "'1"}:
        vector = BitVector(0 if text == "'0" else (1 << context_width) - 1, context_width)
    else:
        try:
            vector = parse_value(text).vector
        except ParseError as exc:
            raise MappingError(f"无法解析映射表达式“{term}”：{exc}") from exc
    if vector.width != context_width:
        raise MappingError(
            f"表达式项 {term} 为 {vector.width} bit，但目标字段为 {context_width} bit"
        )
    return vector


def _evaluate_rhs(source: BitVector, expression: str, context_width: int) -> BitVector:
    text = expression.strip()

    reduction = re.fullmatch(
        r"(?P<op>\^|&|\||~\^)\s*(?P<term>input\[\d+(?::\d+)?\])",
        text,
        re.IGNORECASE,
    )
    if reduction:
        vector = _input_slice(source, reduction.group("term"))
        assert vector is not None
        op = reduction.group("op")
        if op == "^":
            value = vector.value.bit_count() & 1
        elif op == "~^":
            value = (vector.value.bit_count() & 1) ^ 1
        elif op == "&":
            value = int(vector.value == vector.mask)
        else:
            value = int(vector.value != 0)
        result = BitVector(value, 1)
        if context_width != 1:
            raise MappingError(
                f"归约运算 {expression} 的结果为 1 bit，但目标字段为 {context_width} bit"
            )
        return result

    if text.startswith("~"):
        operand = _resolve_term(source, text[1:], context_width)
        return BitVector((~operand.value) & operand.mask, context_width)

    tokens = text.split()
    if len(tokens) == 3 and tokens[1] in {"^", "&", "|", "+", "-"}:
        left = _resolve_term(source, tokens[0], context_width)
        right = _resolve_term(source, tokens[2], context_width)
        operator = tokens[1]
        if operator == "^":
            value = left.value ^ right.value
        elif operator == "&":
            value = left.value & right.value
        elif operator == "|":
            value = left.value | right.value
        elif operator == "+":
            value = left.value + right.value
        else:
            value = left.value - right.value
        return BitVector(value & ((1 << context_width) - 1), context_width)
    if len(tokens) > 1:
        raise MappingError(
            f"无法识别表达式“{expression}”；二元运算请写成“左值 ^ 右值”"
        )
    return _resolve_term(source, text, context_width)


def apply_assignment_mapping(
    source: BitVector,
    specification: str,
    output_width: int | None = None,
) -> MappingResult:
    """Apply explicit SystemVerilog-like output slice assignments.

    Example::

        output[31:24] = input[7:0]
        output[23:20] = input[31:28]
        output[19:16] = 4'h0
        output[15:0]  = input[27:12]
    """

    assignments: list[tuple[str, str]] = []
    for line_number, raw_line in enumerate(specification.splitlines(), start=1):
        line = raw_line.split("//", 1)[0].strip().rstrip(";").strip()
        if not line:
            continue
        if "=" not in line:
            raise MappingError(f"第 {line_number} 行缺少等号：{raw_line.strip()}")
        lhs, rhs = (part.strip() for part in line.split("=", 1))
        assignments.append((lhs, rhs))

    if not assignments:
        raise MappingError("字段映射不能为空")

    parsed_lhs: list[tuple[str, str, int, int, int]] = []
    highest_bit = -1
    for lhs, rhs in assignments:
        match = LHS_RE.fullmatch(lhs)
        if not match:
            raise MappingError(f"输出字段格式错误：{lhs}，应写成 output[MSB:LSB]")
        msb, lsb, width = _parse_range(match, "output")
        highest_bit = max(highest_bit, msb)
        parsed_lhs.append((lhs, rhs, msb, lsb, width))

    final_width = output_width or (highest_bit + 1)
    if final_width <= 0:
        raise MappingError("输出位宽必须大于 0")

    result_value = 0
    assigned_mask = 0
    rows: list[MappingRow] = []
    bit_rows: list[MappingBit] = []
    for lhs, rhs, msb, lsb, lhs_width in parsed_lhs:
        if msb >= final_width:
            raise MappingError(f"{lhs} 超出输出范围 [{final_width - 1}:0]")
        field_mask = ((1 << lhs_width) - 1) << lsb
        overlap = assigned_mask & field_mask
        if overlap:
            overlap_bits = _missing_ranges((~overlap) & ((1 << final_width) - 1), final_width)
            raise MappingError(f"{lhs} 与已有输出字段重叠（重叠位置 {overlap_bits}）")

        rhs_vector = _evaluate_rhs(source, rhs, lhs_width)

        result_value |= rhs_vector.value << lsb
        assigned_mask |= field_mask
        rows.append(MappingRow(lhs, rhs, lhs_width, rhs_vector.to_hex()))
        input_match = RHS_INPUT_RE.fullmatch(rhs)
        input_lsb = None
        if input_match:
            input_lsb = int(input_match.group("lsb")) if input_match.group("lsb") else int(input_match.group("msb"))
        for offset in range(lhs_width):
            if input_lsb is not None:
                bit_expression = f"input[{input_lsb + offset}]"
            elif lhs_width == 1:
                bit_expression = rhs
            else:
                bit_expression = f"({rhs})[{offset}]"
            bit_rows.append(
                MappingBit(
                    output_bit=lsb + offset,
                    expression=bit_expression,
                    value=(rhs_vector.value >> offset) & 1,
                )
            )

    complete_mask = (1 << final_width) - 1
    if assigned_mask != complete_mask:
        missing_mask = complete_mask & ~assigned_mask
        raise MappingError(f"输出字段存在未赋值 bit：{_missing_ranges(~missing_mask & complete_mask, final_width)}")

    return MappingResult(
        BitVector(result_value, final_width),
        tuple(rows),
        tuple(sorted(bit_rows, key=lambda item: item.output_bit, reverse=True)),
    )
