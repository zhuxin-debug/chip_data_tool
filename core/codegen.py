from __future__ import annotations

import re
from typing import Any

from .bit_vector import BitVector
from .errors import OperationError
from .pipeline import run_pipeline


def _safe_identifier(name: str) -> str:
    identifier = re.sub(r"\W+", "_", name.strip())
    if not identifier:
        identifier = "transform_data"
    if identifier[0].isdigit():
        identifier = f"fn_{identifier}"
    return identifier


def _current_expression(expression: str, current_name: str) -> str:
    return re.sub(r"\b(?:input|current)(?=\[)", current_name, expression, flags=re.IGNORECASE)


def _mapping_assignments(specification: str, target: str, current: str) -> list[str]:
    lines: list[str] = [f"  {target} = '0;"]
    for raw_line in specification.splitlines():
        line = raw_line.split("//", 1)[0].strip().rstrip(";").strip()
        if not line:
            continue
        lhs, rhs = (part.strip() for part in line.split("=", 1))
        lhs = re.sub(r"^output", target, lhs, flags=re.IGNORECASE)
        rhs = _current_expression(rhs, current)
        lines.append(f"  {lhs} = {rhs};")
    return lines


def generate_systemverilog(
    source: BitVector,
    steps: list[dict[str, Any]],
    function_name: str = "transform_data",
) -> str:
    result = run_pipeline(source, steps)
    name = _safe_identifier(function_name)
    declarations = [
        f"function automatic logic [{result.final.width - 1}:0] {name}(",
        f"  input logic [{source.width - 1}:0] input_data",
        ");",
    ]
    for stage in result.stages:
        declarations.append(
            f"  logic [{stage.output_vector.width - 1}:0] step_{stage.index};"
        )

    statements: list[str] = []
    current = "input_data"
    current_width = source.width
    for index, (step, stage) in enumerate(zip(steps, result.stages), start=1):
        target = f"step_{index}"
        statements.append(f"  // {stage.description}")
        step_type = step.get("type")
        if step_type == "reverse_bits":
            statements.append(f"  {target} = {{<<{{{current}}}}};")
        elif step_type == "reverse_units":
            unit = int(step["unit_bits"])
            statements.append(f"  {target} = {{<<{unit}{{{current}}}}};")
        elif step_type == "reverse_bits_in_units":
            unit = int(step["unit_bits"])
            statements.append(f"  {target} = '0;")
            statements.append(
                f"  for (int i_{index} = 0; i_{index} < {current_width}; i_{index} += {unit})"
            )
            statements.append(
                f"    for (int j_{index} = 0; j_{index} < {unit}; j_{index}++)"
            )
            statements.append(
                f"      {target}[i_{index}+j_{index}] = {current}[i_{index}+{unit}-1-j_{index}];"
            )
        elif step_type == "extract":
            statements.append(f"  {target} = {current}[{step['msb']}:{step['lsb']}];")
        elif step_type == "mapping":
            statements.extend(
                _mapping_assignments(str(step.get("specification", "")), target, current)
            )
        elif step_type == "binary":
            operators = {"AND": "&", "OR": "|", "XOR": "^", "XNOR": "~^", "ADD": "+", "SUB": "-"}
            operator = operators[str(step["operator"]).upper()]
            operand = _current_expression(str(step["operand"]), current)
            statements.append(f"  {target} = {current} {operator} {operand};")
        elif step_type == "not":
            statements.append(f"  {target} = ~{current};")
        elif step_type == "shift":
            direction = str(step["direction"])
            count = int(step["count"])
            if direction == "left":
                expression = f"{current} << {count}"
            elif direction == "right":
                expression = f"{current} >> {count}"
            else:
                expression = f"$signed({current}) >>> {count}"
            statements.append(f"  {target} = {expression};")
        elif step_type == "rotate":
            direction = str(step["direction"])
            count = int(step["count"]) % current_width
            if count == 0:
                expression = current
            elif direction == "left":
                expression = f"({current} << {count}) | ({current} >> {current_width - count})"
            else:
                expression = f"({current} >> {count}) | ({current} << {current_width - count})"
            statements.append(f"  {target} = {expression};")
        elif step_type == "bit_edit":
            bit = int(step["bit_index"])
            action = str(step["action"])
            statements.append(f"  {target} = {current};")
            value = {"set": "1'b1", "clear": "1'b0"}.get(action)
            if value is not None:
                statements.append(f"  {target}[{bit}] = {value};")
            else:
                statements.append(f"  {target}[{bit}] = ~{current}[{bit}];")
        elif step_type == "bit_logic":
            left_bit = int(step["left_bit"])
            right_bit = int(step["right_bit"])
            target_bit = int(step["target_bit"])
            operator = {"AND": "&", "OR": "|", "XOR": "^", "XNOR": "~^"}[
                str(step["operator"]).upper()
            ]
            statements.append(f"  {target} = {current};")
            statements.append(
                f"  {target}[{target_bit}] = {current}[{left_bit}] {operator} {current}[{right_bit}];"
            )
        elif step_type == "group_reduce":
            group_bits = int(step.get("group_bits", 2))
            operator = {"AND": "&", "OR": "|", "XOR": "^", "XNOR": "~^"}[
                str(step["operator"]).upper()
            ]
            direction = str(step.get("direction", "lsb"))
            statements.append(
                f"  for (int i_{index} = 0; i_{index} < {stage.output_vector.width}; i_{index}++)"
            )
            if direction == "lsb":
                part_select = f"{current}[i_{index}*{group_bits} +: {group_bits}]"
            else:
                part_select = (
                    f"{current}[{current_width}-1-i_{index}*{group_bits} -: {group_bits}]"
                )
            statements.append(f"    {target}[i_{index}] = {operator}{part_select};")
        elif step_type == "append_parity":
            parity = f"^{current}" if step.get("mode") == "even" else f"~^{current}"
            if step.get("position") == "msb":
                statements.append(f"  {target} = {{{parity}, {current}}};")
            else:
                statements.append(f"  {target} = {{{current}, {parity}}};")
        else:
            raise OperationError(f"无法为操作 {step_type} 生成 SystemVerilog")
        current = target
        current_width = stage.output_vector.width

    statements.append(f"  {name} = {current};")
    return "\n".join(declarations + [""] + statements + ["endfunction", ""])
