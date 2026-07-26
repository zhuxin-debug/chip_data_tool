from __future__ import annotations

import re

from .bit_vector import BitVector
from .errors import OperationError
from .parser import parse_value


INPUT_RANGE_RE = re.compile(
    r"^(?:input|current)\[(?P<msb>\d+)(?::(?P<lsb>\d+))?\]$",
    re.IGNORECASE,
)


def _validate_unit_width(vector: BitVector, unit_bits: int) -> None:
    if not isinstance(unit_bits, int) or unit_bits <= 0:
        raise OperationError("操作单位必须是大于 0 的整数")
    if vector.width % unit_bits:
        raise OperationError(
            f"当前数据为 {vector.width} bit，不能按 {unit_bits} bit 完整分组"
        )


def reverse_all_bits(vector: BitVector) -> BitVector:
    reversed_value = int(f"{vector.value:0{vector.width}b}"[::-1], 2)
    return BitVector(reversed_value, vector.width, vector.signed)


def reverse_unit_order(vector: BitVector, unit_bits: int) -> BitVector:
    """Reverse unit order while preserving the bits inside each unit."""

    _validate_unit_width(vector, unit_bits)
    unit_mask = (1 << unit_bits) - 1
    result = 0
    for offset in range(0, vector.width, unit_bits):
        result = (result << unit_bits) | ((vector.value >> offset) & unit_mask)
    return BitVector(result, vector.width, vector.signed)


def reverse_bits_in_units(vector: BitVector, unit_bits: int) -> BitVector:
    """Reverse bits inside every unit without changing unit positions."""

    _validate_unit_width(vector, unit_bits)
    unit_mask = (1 << unit_bits) - 1
    result = 0
    for offset in range(0, vector.width, unit_bits):
        unit = (vector.value >> offset) & unit_mask
        reversed_unit = int(f"{unit:0{unit_bits}b}"[::-1], 2)
        result |= reversed_unit << offset
    return BitVector(result, vector.width, vector.signed)


def extract_bits(vector: BitVector, msb: int, lsb: int) -> BitVector:
    try:
        return vector.slice(msb, lsb)
    except ValueError as exc:
        raise OperationError(str(exc)) from exc


def resolve_operand(vector: BitVector, expression: str) -> BitVector:
    """Resolve a constant or a slice of the current pipeline value."""

    text = expression.strip()
    match = INPUT_RANGE_RE.fullmatch(text)
    if match:
        msb = int(match.group("msb"))
        lsb = int(match.group("lsb")) if match.group("lsb") is not None else msb
        return extract_bits(vector, msb, lsb)
    try:
        return parse_value(text).vector
    except ValueError as exc:
        raise OperationError(f"无法解析运算数“{expression}”：{exc}") from exc


def _operand_value(vector: BitVector, expression: str) -> int:
    operand = resolve_operand(vector, expression)
    if operand.value > vector.mask:
        raise OperationError(
            f"运算数 {operand.to_sv_hex()} 超出当前 {vector.width} bit 数据范围"
        )
    return operand.value


def binary_operation(vector: BitVector, operator: str, operand: str) -> BitVector:
    """Apply a width-preserving hardware-style binary operation.

    ADD and SUB wrap to the current width, matching ordinary RTL assignment
    truncation. Shorter operands are zero-extended.
    """

    rhs = _operand_value(vector, operand)
    op = operator.upper()
    if op == "AND":
        result = vector.value & rhs
    elif op == "OR":
        result = vector.value | rhs
    elif op == "XOR":
        result = vector.value ^ rhs
    elif op == "XNOR":
        result = ~(vector.value ^ rhs)
    elif op == "ADD":
        result = vector.value + rhs
    elif op == "SUB":
        result = vector.value - rhs
    else:
        raise OperationError(f"不支持的二元运算：{operator}")
    return BitVector(result & vector.mask, vector.width, vector.signed)


def group_reduce(
    vector: BitVector,
    operator: str,
    group_bits: int = 2,
    direction: str = "lsb",
) -> BitVector:
    """Reduce each fixed-width group to one output bit.

    With the default LSB-first order, output[0] is the reduction of
    input[group_bits-1:0]. MSB-first order places the highest input group in
    output[0], which is useful for stream-oriented display conventions.
    """

    _validate_unit_width(vector, group_bits)
    normalized_operator = operator.upper()
    if normalized_operator not in {"AND", "OR", "XOR", "XNOR"}:
        raise OperationError(f"不支持的分组归约运算：{operator}")

    normalized_direction = direction.lower()
    if normalized_direction not in {"lsb", "msb"}:
        raise OperationError(f"不支持的分组方向：{direction}")

    group_count = vector.width // group_bits
    group_mask = (1 << group_bits) - 1
    result = 0
    for output_bit in range(group_count):
        group_index = output_bit if normalized_direction == "lsb" else group_count - 1 - output_bit
        group_value = (vector.value >> (group_index * group_bits)) & group_mask
        if normalized_operator == "AND":
            reduced_bit = int(group_value == group_mask)
        elif normalized_operator == "OR":
            reduced_bit = int(group_value != 0)
        else:
            reduced_bit = group_value.bit_count() & 1
            if normalized_operator == "XNOR":
                reduced_bit ^= 1
        result |= reduced_bit << output_bit
    return BitVector(result, group_count)


def invert_bits(vector: BitVector) -> BitVector:
    return BitVector((~vector.value) & vector.mask, vector.width, vector.signed)


def shift_bits(vector: BitVector, direction: str, count: int) -> BitVector:
    if count < 0:
        raise OperationError("移位数量不能为负数")
    normalized = direction.lower()
    if normalized == "left":
        result = (vector.value << count) & vector.mask
    elif normalized == "right":
        result = vector.value >> count
    elif normalized == "arithmetic_right":
        result = (vector.twos_complement_value >> count) & vector.mask
    else:
        raise OperationError(f"不支持的移位方向：{direction}")
    return BitVector(result, vector.width, vector.signed)


def rotate_bits(vector: BitVector, direction: str, count: int) -> BitVector:
    if count < 0:
        raise OperationError("循环移位数量不能为负数")
    count %= vector.width
    if count == 0:
        return vector
    normalized = direction.lower()
    if normalized == "left":
        result = ((vector.value << count) | (vector.value >> (vector.width - count))) & vector.mask
    elif normalized == "right":
        result = ((vector.value >> count) | (vector.value << (vector.width - count))) & vector.mask
    else:
        raise OperationError(f"不支持的循环移位方向：{direction}")
    return BitVector(result, vector.width, vector.signed)


def edit_bit(vector: BitVector, bit_index: int, action: str) -> BitVector:
    if bit_index < 0 or bit_index >= vector.width:
        raise OperationError(
            f"bit[{bit_index}] 超出当前数据范围 [{vector.width - 1}:0]"
        )
    bit_mask = 1 << bit_index
    normalized = action.lower()
    if normalized == "set":
        result = vector.value | bit_mask
    elif normalized == "clear":
        result = vector.value & ~bit_mask
    elif normalized == "toggle":
        result = vector.value ^ bit_mask
    else:
        raise OperationError(f"不支持的 bit 编辑操作：{action}")
    return BitVector(result & vector.mask, vector.width, vector.signed)


def bit_logic_operation(
    vector: BitVector,
    left_bit: int,
    operator: str,
    right_bit: int,
    target_bit: int,
) -> BitVector:
    """Apply logic to two selected bits and write the result to a target bit."""

    for name, bit_index in (
        ("左操作数", left_bit),
        ("右操作数", right_bit),
        ("目标", target_bit),
    ):
        if bit_index < 0 or bit_index >= vector.width:
            raise OperationError(
                f"{name} bit[{bit_index}] 超出当前数据范围 [{vector.width - 1}:0]"
            )

    left = (vector.value >> left_bit) & 1
    right = (vector.value >> right_bit) & 1
    normalized = operator.upper()
    if normalized == "AND":
        result_bit = left & right
    elif normalized == "OR":
        result_bit = left | right
    elif normalized == "XOR":
        result_bit = left ^ right
    elif normalized == "XNOR":
        result_bit = (left ^ right) ^ 1
    else:
        raise OperationError(f"不支持的单 bit 逻辑运算：{operator}")

    target_mask = 1 << target_bit
    value = vector.value & ~target_mask
    value |= result_bit << target_bit
    return BitVector(value & vector.mask, vector.width, vector.signed)
