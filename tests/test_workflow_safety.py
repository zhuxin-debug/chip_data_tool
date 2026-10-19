import json

import pytest

from core import BitVector, DataToolError, generate_systemverilog, parse_value, run_pipeline
from core.checksum import CRC_PRESETS, CRCPreset, calculate_crc
from core.provenance import bit_sources, mapping_html, trace_original
from core.templates import load_template, save_template, validate_template
from core.validation import validate_steps
from core.workspace import DEFAULTS, fingerprint, validate_workspace, workspace_document


@pytest.mark.parametrize("steps", [[None], [{}], [1], [{"type": []}],
    [{"type": "shift", "direction": "diagonal", "count": 0}],
    [{"type": "extract", "msb": 7.5, "lsb": 0}],
    [{"type": "extract", "msb": True, "lsb": 0}],
    [{"type": "resize", "width": 0, "mode": "zero"}],
    [{"type": "not", "enabled": "false"}],
    [{"type": "binary", "operator": "OR", "operand": None}]])
def test_invalid_steps_produce_user_errors(steps):
    with pytest.raises(DataToolError, match="第 1 步"):
        run_pipeline(BitVector(1, 8), steps)


@pytest.mark.parametrize("document", [None, [], {"version": True, "steps": []},
    {"version": 1, "steps": [None]},
    {"version": 1, "steps": [], "input_defaults": {"width": 8.5}},
    {"version": 1, "steps": [], "input_defaults": {"format_hint": "wrong"}}])
def test_templates_are_validated_before_loading(tmp_path, document):
    (tmp_path / "bad.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DataToolError):
        load_template(tmp_path, "bad")


def test_template_overwrite_is_explicit(tmp_path):
    original = {"steps": [{"type": "not"}]}
    path = save_template(tmp_path, "example", original)
    with pytest.raises(DataToolError, match="同名"):
        save_template(tmp_path, "example", {"steps": []})
    assert load_template(tmp_path, path.stem)["steps"] == original["steps"]
    save_template(tmp_path, "example", {"steps": []}, overwrite=True)
    assert load_template(tmp_path, path.stem)["steps"] == []


def test_workspace_roundtrip_and_invalid_import():
    state = dict(DEFAULTS, raw_value="8'hA5", steps=[{"type": "not"}], compare_expected="8'h5A")
    assert validate_workspace(workspace_document(state)) == state
    bad = workspace_document(state)
    bad["state"]["input_width"] = 8.5
    with pytest.raises(DataToolError):
        validate_workspace(bad)
    assert state["input_width"] == 0
    assert fingerprint(state) == fingerprint(dict(reversed(list(state.items()))))


@pytest.mark.parametrize("operand,canonical", [("0xFF", "8'hFF"), ("FF", "8'hFF"),
    ("0b1010", "4'hA"), ("-1", "8'hFF"), ("8'shFF", "8'hFF")])
def test_codegen_uses_parsed_unsigned_bit_patterns(operand, canonical):
    code = generate_systemverilog(BitVector(0xA5, 8), [{"type": "binary", "operator": "XOR", "operand": operand}])
    assert f"input_data ^ {canonical};" in code


def test_mapping_codegen_normalizes_literals_and_keeps_dynamic_fields():
    code = generate_systemverilog(BitVector(0x12, 8), [{"type": "mapping",
        "specification": "output[7:0] = input[7:0] ^ 0xFF"}])
    assert "step_1[7:0] = input_data[7:0] ^ 8'hFF;" in code


def test_disabled_step_preserves_stage_number_and_codegen():
    steps = [{"type": "not", "enabled": False}, {"type": "not"}]
    result = run_pipeline(BitVector(0xA5, 8), steps)
    assert result.final.value == 0x5A
    assert len(result.stages) == 2
    assert "step_1 = input_data;" in generate_systemverilog(result.source, steps)
    assert trace_original(result, steps, 3) == {3}


@pytest.mark.parametrize("name", ["module", "function", "input_data", "step_1", "123", "$name", "中文"])
def test_codegen_identifiers_are_safe(name):
    code = generate_systemverilog(BitVector(0, 1), [], name)
    assert f"] {name}(" not in code


def test_resize_and_arithmetic_diagnostics():
    result = run_pipeline(BitVector(0x80, 8), [{"type": "resize", "mode": "sign", "width": 16}])
    assert result.final.value == 0xFF80
    result = run_pipeline(BitVector(0x80, 8), [{"type": "resize", "mode": "zero", "width": 16}])
    assert result.final.value == 0x0080
    result = run_pipeline(BitVector(0xFF, 8), [{"type": "binary", "operator": "ADD", "operand": "1"}])
    assert result.final.value == 0
    assert any("进位" in note for note in result.stages[0].notes)
    result = run_pipeline(BitVector(0, 8), [{"type": "binary", "operator": "SUB", "operand": "1"}])
    assert result.final.value == 255
    assert any("借位" in note for note in result.stages[0].notes)
    result = run_pipeline(BitVector(127, 8), [{"type": "binary", "operator": "ADD", "operand": "1"}])
    assert any("溢出" in note for note in result.stages[0].notes)


def test_crc_order_is_independent_of_reflection():
    vector = BitVector(0x12345678, 32)
    reversed_bytes = BitVector(0x78563412, 32)
    for preset in CRC_PRESETS.values():
        assert calculate_crc(vector, preset, "little") == calculate_crc(reversed_bytes, preset)
    with pytest.raises(DataToolError):
        calculate_crc(vector, CRCPreset("invalid", 16, 0x11021, 0, False, False, 0))


def test_zero_declared_width_is_rejected():
    with pytest.raises(DataToolError):
        parse_value("0'h1")


CASES = [
    {"type": "reverse_bits"}, {"type": "reverse_units", "unit_bits": 4},
    {"type": "reverse_bits_in_units", "unit_bits": 4}, {"type": "extract", "msb": 6, "lsb": 2},
    {"type": "not"}, {"type": "shift", "direction": "left", "count": 3},
    {"type": "shift", "direction": "arithmetic_right", "count": 3},
    {"type": "rotate", "direction": "right", "count": 3},
    {"type": "bit_edit", "action": "set", "bit_index": 2},
    {"type": "bit_logic", "operator": "XOR", "left_bit": 7, "right_bit": 3, "target_bit": 1},
    {"type": "group_reduce", "operator": "XOR", "group_bits": 2, "direction": "msb"},
    {"type": "append_parity", "mode": "odd", "position": "lsb"},
    {"type": "resize", "mode": "sign", "width": 12},
    {"type": "resize", "mode": "zero", "width": 12},
    {"type": "resize", "mode": "truncate", "width": 4},
    {"type": "binary", "operator": "ADD", "operand": "input[4:1]"},
    {"type": "binary", "operator": "ADD", "operand": "input[7:4]"},
    {"type": "mapping", "specification": "output[3:0] = input[7:4] + input[3:0]"},
    {"type": "mapping", "specification": "output[3] = ^input[7:0]\noutput[2:1] = ~input[1:0]\noutput[0] = '1"},
]


@pytest.mark.parametrize("step", CASES)
def test_provenance_covers_every_observed_input_dependency(step):
    step = validate_steps([step])[0]
    # For every input vector, flip each input bit. Any changed output must name
    # that input as a structural dependency (values themselves come from core).
    for value in range(256):
        baseline = run_pipeline(BitVector(value, 8), [step])
        sources = [trace_original(baseline, [step], b) for b in range(baseline.final.width)]
        for input_bit in range(8):
            changed = run_pipeline(BitVector(value ^ (1 << input_bit), 8), [step]).final.value ^ baseline.final.value
            for bit in range(baseline.final.width):
                if changed >> bit & 1:
                    assert input_bit in sources[bit], (step, value, bit, input_bit)


def test_multi_stage_provenance_and_portable_map():
    steps = [{"type": "reverse_units", "unit_bits": 8}, {"type": "extract", "msb": 7, "lsb": 0}]
    result = run_pipeline(BitVector(0x1234, 16), steps)
    assert trace_original(result, steps, 0) == {8}
    assert trace_original(result, steps, 7) == {15}
    html = mapping_html(result, steps)
    assert "__MAPPING_DATA__" not in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html


def test_wide_mapping_and_values_remain_exact():
    source = BitVector((1 << 4095) | 1, 4096)
    steps = [{"type": "reverse_bits"}]
    result = run_pipeline(source, steps)
    assert result.final == source
    assert bit_sources(result.stages[0], steps[0], 0)[0] == [[4095, 4095]]
    assert trace_original(result, steps, 4095) == {0}
