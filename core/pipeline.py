from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bit_vector import BitVector
from .checksum import append_parity
from .errors import DataToolError, OperationError
from .mapping import MappingBit, MappingRow, apply_assignment_mapping
from .operations import (
    bit_logic_operation,
    binary_operation,
    edit_bit,
    extract_bits,
    group_reduce,
    invert_bits,
    reverse_all_bits,
    reverse_bits_in_units,
    reverse_unit_order,
    rotate_bits,
    shift_bits,
    resize_bits,
    resolve_operand,
)
from .validation import validate_steps


@dataclass(frozen=True, slots=True)
class PipelineStage:
    index: int
    description: str
    input_vector: BitVector
    output_vector: BitVector
    mapping_rows: tuple[MappingRow, ...] = ()
    mapping_bits: tuple[MappingBit, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineResult:
    source: BitVector
    final: BitVector
    stages: tuple[PipelineStage, ...]


def describe_step(step: dict[str, Any]) -> str:
    step_type = step.get("type")
    if step_type == "resize":
        names = {"zero": "补零扩展", "sign": "符号扩展", "truncate": "保留低位截断"}
        return f"{names.get(step.get('mode'), '位宽转换')}至 {step.get('width')} bit"
    if step_type == "reverse_bits":
        return "整体 bit 反向"
    if step_type == "reverse_units":
        unit = int(step.get("unit_bits", 8))
        names = {4: "Nibble", 8: "Byte", 16: "16-bit Word", 32: "32-bit Word"}
        return f"按 {names.get(unit, f'{unit}-bit 单元')}反向排列"
    if step_type == "reverse_bits_in_units":
        unit = int(step.get("unit_bits", 8))
        return f"每个 {unit}-bit 单元内部 bit 反向"
    if step_type == "extract":
        return f"提取 [{step.get('msb')}:{step.get('lsb')}]"
    if step_type == "mapping":
        width = step.get("output_width")
        return f"字段映射{f'（输出 {width} bit）' if width else ''}"
    if step_type == "binary":
        return f"{str(step.get('operator', '')).upper()} {step.get('operand', '')}"
    if step_type == "not":
        return "按位取反 NOT"
    if step_type == "shift":
        names = {"left": "逻辑左移", "right": "逻辑右移", "arithmetic_right": "算术右移"}
        return f"{names.get(str(step.get('direction')), '移位')} {step.get('count')} bit"
    if step_type == "rotate":
        name = "循环左移" if step.get("direction") == "left" else "循环右移"
        return f"{name} {step.get('count')} bit"
    if step_type == "bit_edit":
        names = {"set": "置 1", "clear": "清 0", "toggle": "翻转"}
        return f"bit[{step.get('bit_index')}] {names.get(str(step.get('action')), '')}"
    if step_type == "bit_logic":
        return (
            f"bit[{step.get('target_bit')}] = bit[{step.get('left_bit')}] "
            f"{str(step.get('operator', '')).upper()} bit[{step.get('right_bit')}]"
        )
    if step_type == "group_reduce":
        direction = "从 LSB" if step.get("direction", "lsb") == "lsb" else "从 MSB"
        return (
            f"{direction} 每 {step.get('group_bits', 2)} bit 分组"
            f"归约 {str(step.get('operator', '')).upper()}"
        )
    if step_type == "append_parity":
        mode = "偶校验" if step.get("mode") == "even" else "奇校验"
        position = "MSB" if step.get("position") == "msb" else "LSB"
        return f"在 {position} 追加 {mode} bit"
    return f"未知操作：{step_type}"


def _positive_int(value: Any, name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise OperationError(f"{name} 必须是整数") from exc
    if result <= 0:
        raise OperationError(f"{name} 必须大于 0")
    return result


def _nonnegative_int(value: Any, name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise OperationError(f"{name} 必须是整数") from exc
    if result < 0:
        raise OperationError(f"{name} 不能为负数")
    return result


def run_pipeline(source: BitVector, steps: list[dict[str, Any]]) -> PipelineResult:
    steps = validate_steps(steps)
    current = source
    stages: list[PipelineStage] = []
    for index, step in enumerate(steps, start=1):
        if not step.get("enabled", True):
            stages.append(PipelineStage(index, f"已停用 · {describe_step(step)}", current, current))
            continue
        step_type = step.get("type")
        before = current
        mapping_rows: tuple[MappingRow, ...] = ()
        mapping_bits: tuple[MappingBit, ...] = ()
        notes: list[str] = []
        try:
            if step_type == "reverse_bits":
                current = reverse_all_bits(current)
            elif step_type == "reverse_units":
                current = reverse_unit_order(current, _positive_int(step.get("unit_bits"), "操作单位"))
            elif step_type == "reverse_bits_in_units":
                current = reverse_bits_in_units(current, _positive_int(step.get("unit_bits"), "操作单位"))
            elif step_type == "extract":
                try:
                    msb = int(step.get("msb"))
                    lsb = int(step.get("lsb"))
                except (TypeError, ValueError) as exc:
                    raise OperationError("字段 MSB 和 LSB 必须是整数") from exc
                current = extract_bits(current, msb, lsb)
            elif step_type == "mapping":
                output_width_raw = step.get("output_width")
                output_width = _positive_int(output_width_raw, "输出位宽") if output_width_raw else None
                mapping = apply_assignment_mapping(current, str(step.get("specification", "")), output_width)
                current = mapping.vector
                mapping_rows = mapping.rows
                mapping_bits = mapping.bits
            elif step_type == "binary":
                current = binary_operation(
                    current,
                    str(step.get("operator", "")),
                    str(step.get("operand", "")),
                )
                rhs = resolve_operand(before, step["operand"]).value
                if step["operator"] in {"ADD", "SUB"}:
                    full = before.value + rhs if step["operator"] == "ADD" else before.value - rhs
                    if full > before.mask:
                        notes.append("发生进位：结果已按当前位宽截断")
                    if full < 0:
                        notes.append("发生借位：结果已按当前位宽回绕")
                    rhs_signed = BitVector(rhs, before.width).twos_complement_value
                    signed_full = before.twos_complement_value + (rhs_signed if step["operator"] == "ADD" else -rhs_signed)
                    if not -(1 << (before.width - 1)) <= signed_full < (1 << (before.width - 1)):
                        notes.append("按有符号补码解释时发生溢出")
            elif step_type == "not":
                current = invert_bits(current)
            elif step_type == "shift":
                current = shift_bits(
                    current,
                    str(step.get("direction", "")),
                    _nonnegative_int(step.get("count"), "移位数量"),
                )
            elif step_type == "rotate":
                current = rotate_bits(
                    current,
                    str(step.get("direction", "")),
                    _nonnegative_int(step.get("count"), "循环移位数量"),
                )
            elif step_type == "bit_edit":
                current = edit_bit(
                    current,
                    _nonnegative_int(step.get("bit_index"), "bit 编号"),
                    str(step.get("action", "")),
                )
            elif step_type == "bit_logic":
                current = bit_logic_operation(
                    current,
                    _nonnegative_int(step.get("left_bit"), "左操作数 bit 编号"),
                    str(step.get("operator", "")),
                    _nonnegative_int(step.get("right_bit"), "右操作数 bit 编号"),
                    _nonnegative_int(step.get("target_bit"), "目标 bit 编号"),
                )
            elif step_type == "group_reduce":
                current = group_reduce(
                    current,
                    str(step.get("operator", "")),
                    _positive_int(step.get("group_bits", 2), "每组位数"),
                    str(step.get("direction", "lsb")),
                )
            elif step_type == "append_parity":
                current = append_parity(
                    current,
                    str(step.get("mode", "even")),
                    str(step.get("position", "lsb")),
                )
            elif step_type == "resize":
                current = resize_bits(current, step["width"], step["mode"])
                if step["width"] < before.width:
                    notes.append(f"已丢弃高 {before.width - step['width']} bit；保留低 {step['width']} bit")
            else:
                raise OperationError(f"第 {index} 步包含未知操作：{step_type}")
        except (DataToolError, ValueError) as exc:
            raise OperationError(f"第 {index} 步（{describe_step(step)}）：{exc}") from exc
        stages.append(
            PipelineStage(
                index,
                describe_step(step),
                before,
                current,
                mapping_rows,
                mapping_bits,
                tuple(notes),
            )
        )
    return PipelineResult(source, current, tuple(stages))
