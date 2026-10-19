"""Structural bit dependencies, kept separate from displayed bit values.

Ranges are inclusive (low, high). Arithmetic includes the carry/borrow chain;
this is a dependency map, not a claim that each output has one direct wire.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .operations import INPUT_RANGE_RE
from .pipeline import PipelineResult, PipelineStage
from .validation import validate_steps


def _term_ranges(term: str, offset: int, carry: bool = False) -> list[list[int]]:
    match = INPUT_RANGE_RE.fullmatch(term.strip())
    if not match:
        return []
    high = int(match["msb"])
    low = int(match["lsb"]) if match["lsb"] is not None else high
    if low + offset > high and not carry:
        return []
    return [[low if carry else low + offset, min(high, low + offset)]]


def _expression_ranges(expression: str, offset: int) -> list[list[int]]:
    reduction = re.fullmatch(r"(?:~\^|\^|&|\|)\s*(input\[\d+(?::\d+)?\])", expression, re.I)
    if reduction:
        match = INPUT_RANGE_RE.fullmatch(reduction[1])
        high = int(match["msb"])
        low = int(match["lsb"]) if match["lsb"] is not None else high
        return [[low, high]]
    if expression.startswith("~"):
        return _term_ranges(expression[1:], offset)
    tokens = expression.split()
    if len(tokens) == 3:
        return _term_ranges(tokens[0], offset, tokens[1] in {"+", "-"}) + _term_ranges(tokens[2], offset, tokens[1] in {"+", "-"})
    return _term_ranges(expression, offset)


def bit_sources(stage: PipelineStage, step: dict[str, Any], bit: int) -> tuple[list[list[int]], str]:
    if not 0 <= bit < stage.output_vector.width:
        raise ValueError("输出 bit 越界")
    width = stage.input_vector.width
    kind = step["type"]
    expression = f"input[{bit}]"
    ranges = [[bit, bit]]
    if not step.get("enabled", True):
        return ranges, expression + "（步骤停用）"
    if kind == "reverse_bits":
        ranges = [[width - 1 - bit, width - 1 - bit]]
    elif kind in {"reverse_units", "reverse_bits_in_units"}:
        unit = step["unit_bits"]
        source = ((width // unit - 1 - bit // unit) * unit + bit % unit if kind == "reverse_units"
                  else bit // unit * unit + unit - 1 - bit % unit)
        ranges = [[source, source]]
    elif kind == "extract":
        ranges = [[bit + step["lsb"], bit + step["lsb"]]]
    elif kind == "mapping":
        for row in stage.mapping_rows:
            indices = [int(x) for x in re.findall(r"\d+", row.output_range)]
            high, low = indices[0], indices[-1]
            if low <= bit <= high:
                return _expression_ranges(row.source, bit - low), f"({row.source}) 的 bit[{bit - low}]"
    elif kind == "binary":
        carry = step["operator"] in {"ADD", "SUB"}
        ranges = [[0 if carry else bit, bit]] + _term_ranges(step["operand"], bit, carry)
        expression = f"input {step['operator']} {step['operand']}" + ("（含低位进位/借位依赖）" if carry else "")
    elif kind == "not":
        expression = f"~input[{bit}]"
    elif kind == "shift":
        count = step["count"]
        source = bit - count if step["direction"] == "left" else bit + count
        if source >= width and step["direction"] == "arithmetic_right":
            source = width - 1
        ranges = [[source, source]] if 0 <= source < width else []
    elif kind == "rotate":
        source = (bit + (-step["count"] if step["direction"] == "left" else step["count"])) % width
        ranges = [[source, source]]
    elif kind == "bit_edit" and bit == step["bit_index"]:
        if step["action"] == "toggle":
            expression = f"~input[{bit}]"
        else:
            ranges = []
    elif kind == "bit_logic" and bit == step["target_bit"]:
        ranges = [[step["left_bit"], step["left_bit"]], [step["right_bit"], step["right_bit"]]]
        expression = f"input[{step['left_bit']}] {step['operator']} input[{step['right_bit']}]"
    elif kind == "group_reduce":
        group = bit if step["direction"] == "lsb" else stage.output_vector.width - 1 - bit
        low = group * step["group_bits"]
        ranges = [[low, low + step["group_bits"] - 1]]
        expression = f"{step['operator']} 归约 input[{ranges[0][1]}:{low}]"
    elif kind == "append_parity":
        parity_bit = width if step["position"] == "msb" else 0
        if bit == parity_bit:
            ranges = [[0, width - 1]]
            expression = f"{step['mode']} parity（归约全部输入）"
        elif step["position"] == "lsb":
            ranges = [[bit - 1, bit - 1]]
    elif kind == "resize" and bit >= width:
        ranges = [[width - 1, width - 1]] if step["mode"] == "sign" else []
    if not ranges:
        expression = f"常量 {stage.output_vector.value >> bit & 1}"
    elif expression == f"input[{bit}]":
        expression = ", ".join(f"input[{hi}:{lo}]" if lo != hi else f"input[{lo}]" for lo, hi in ranges)
    return ranges, expression


def trace_original(result: PipelineResult, steps: list[dict[str, Any]], output_bit: int) -> set[int]:
    steps = validate_steps(steps)
    if not 0 <= output_bit < result.final.width:
        raise ValueError("输出 bit 越界")
    bits = {output_bit}
    for stage, step in reversed(list(zip(result.stages, steps))):
        bits = {source for bit in bits for low, high in bit_sources(stage, step, bit)[0] for source in range(low, high + 1)}
    return bits


def mapping_html(result: PipelineResult, steps: list[dict[str, Any]]) -> str:
    steps = validate_steps(steps)
    stages = []
    for stage, step in zip(result.stages, steps):
        stages.append({"name": f"第 {stage.index} 步 · {stage.description}",
                       "input": stage.input_vector.binary_digits(False),
                       "output": stage.output_vector.binary_digits(False),
                       "rules": [bit_sources(stage, step, bit) for bit in range(stage.output_vector.width)]})
    if not stages:
        bits = result.source.binary_digits(False)
        stages = [{"name": "原始输入（直通）", "input": bits, "output": bits,
                   "rules": [([[i, i]], f"input[{i}]") for i in range(len(bits))]}]
    data = json.dumps({"stages": stages}, ensure_ascii=False).replace("<", "\\u003c")
    template = Path(__file__).resolve().parent.parent / "ui" / "bit_mapping.html"
    return template.read_text(encoding="utf-8").replace("__MAPPING_DATA__", data)
