"""Validate documents and operations before changing state or calculating."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import OperationError


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OperationError(f"{name} 必须是整数")
    if value < minimum:
        raise OperationError(f"{name} 必须大于等于 {minimum}")
    return value


def validate_steps(steps: Any) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        raise OperationError("流水线必须是步骤列表")
    if len(steps) > 200:
        raise OperationError("流水线最多支持 200 步")
    normalized = []
    simple = {"reverse_bits", "not"}
    integers = {
        "reverse_units": {"unit_bits": (None, 1)},
        "reverse_bits_in_units": {"unit_bits": (None, 1)},
        "extract": {"msb": (None, 0), "lsb": (None, 0)},
        "mapping": {"output_width": (0, 0)},
        "shift": {"count": (None, 0)},
        "rotate": {"count": (None, 0)},
        "bit_edit": {"bit_index": (None, 0)},
        "bit_logic": {"left_bit": (None, 0), "right_bit": (None, 0), "target_bit": (None, 0)},
        "group_reduce": {"group_bits": (2, 1)},
        "resize": {"width": (None, 1)},
    }
    enums = {
        "binary": {"operator": (None, ["XOR", "AND", "OR", "XNOR", "ADD", "SUB"])},
        "bit_logic": {"operator": (None, ["XOR", "AND", "OR", "XNOR"])},
        "group_reduce": {"operator": (None, ["XOR", "AND", "OR", "XNOR"]), "direction": ("lsb", ["lsb", "msb"])},
        "shift": {"direction": (None, ["left", "right", "arithmetic_right"])},
        "rotate": {"direction": (None, ["left", "right"])},
        "bit_edit": {"action": (None, ["set", "clear", "toggle"])},
        "append_parity": {"mode": ("even", ["even", "odd"]), "position": ("lsb", ["lsb", "msb"])},
        "resize": {"mode": ("zero", ["zero", "sign", "truncate"])},
    }
    for index, original in enumerate(steps, 1):
        try:
            if not isinstance(original, dict):
                raise OperationError("步骤必须是对象")
            step = deepcopy(original)
            kind = step.get("type")
            if not isinstance(kind, str) or kind not in simple | integers.keys() | enums.keys():
                raise OperationError(f"未知操作：{kind}")
            if not isinstance(step.get("enabled", True), bool):
                raise OperationError("enabled 必须是布尔值")
            for field, (default, minimum) in integers.get(kind, {}).items():
                value = step.get(field, default)
                if field == "output_width" and value is None:
                    value = 0
                step[field] = integer(value, field, minimum)
            for field, (default, choices) in enums.get(kind, {}).items():
                value = step.get(field, default)
                if not isinstance(value, str):
                    raise OperationError(f"{field} 必须为 {' / '.join(choices)}")
                value = value.upper() if field == "operator" else value.lower()
                if value not in choices:
                    raise OperationError(f"{field} 必须为 {' / '.join(choices)}")
                step[field] = value
            for field in {"binary": ["operand"], "mapping": ["specification"]}.get(kind, []):
                if not isinstance(step.get(field), str) or not step[field].strip():
                    raise OperationError(f"{field} 不能为空，且必须是文本")
            if kind == "extract" and step["msb"] < step["lsb"]:
                raise OperationError("MSB 不能小于 LSB")
            normalized.append(step)
        except OperationError as exc:
            raise OperationError(f"第 {index} 步：{exc}") from exc
    return normalized
