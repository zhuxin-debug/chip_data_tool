"""Compile generated SV and compare constant evaluation with the Python engine.

Install requirements-dev.txt to enable this additional EDA check. This is
language-level constant evaluation, not a time-based testbench simulation.
"""
import pytest

from core import BitVector, generate_systemverilog, run_pipeline
from test_workflow_safety import CASES

ps = pytest.importorskip("pyslang")

EXTRA = [
    {"type": "binary", "operator": op, "operand": "0x0F"}
    for op in ["AND", "OR", "XOR", "XNOR", "ADD", "SUB"]
] + [
    {"type": "binary", "operator": "XOR", "operand": "8'shFF"},
    {"type": "shift", "direction": "right", "count": 20},
    {"type": "rotate", "direction": "left", "count": 0},
    {"type": "mapping", "specification": "output[7:0] = input[7:0] ^ FF"},
    {"type": "not", "enabled": False},
]


def evaluate(steps, values, source_width=8):
    source = BitVector(values[0], source_width)
    width = run_pipeline(source, steps).final.width
    code = "module tb;\n" + generate_systemverilog(source, steps)
    for index, value in enumerate(values):
        literal = BitVector(value, source_width).to_sv_hex()
        code += f"localparam logic [{width-1}:0] R{index} = transform_data({literal});\n"
    code += "endmodule\n"
    compilation = ps.ast.Compilation()
    compilation.addSyntaxTree(ps.syntax.SyntaxTree.fromText(code))
    body = compilation.getRoot().topInstances[0].body
    errors = [str(d.code) for d in compilation.getAllDiagnostics() if d.isError()]
    assert not errors, (steps, errors, code)
    for index, value in enumerate(values):
        actual = body.find(f"R{index}").value
        assert not actual.hasUnknown(), (steps, index)
        expected = run_pipeline(BitVector(value, source_width), steps).final.value
        assert int(actual.value) == expected, (steps, value, actual, expected)


@pytest.mark.parametrize("step", CASES + EXTRA)
def test_generated_sv_matches_python_for_all_byte_values(step):
    evaluate([step], list(range(256)))


def test_generated_sv_multistage_dynamic_fields_and_signed_extension():
    evaluate([
        {"type": "binary", "operator": "XOR", "operand": "0xFF"},
        {"type": "not", "enabled": False},
        {"type": "rotate", "direction": "left", "count": 3},
        {"type": "resize", "width": 16, "mode": "sign"},
        {"type": "mapping", "specification": "output[7:0] = input[15:8] + input[7:0]"},
        {"type": "append_parity"},
    ], list(range(256)))


def test_generated_sv_preserves_wide_values():
    evaluate([{"type": "reverse_units", "unit_bits": 8},
              {"type": "binary", "operator": "XOR", "operand": "input[127:0]"}],
             [0, 1, (1 << 255) | 0x1234, (1 << 256) - 1], source_width=256)
