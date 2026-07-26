import pytest

from core import BitVector, MappingError, apply_assignment_mapping, run_pipeline


SPECIFICATION = """
output[31:24] = input[7:0]
output[23:20] = input[31:28]
output[19:16] = 4'h0
output[15:0]  = input[27:12]
"""


def test_assignment_mapping() -> None:
    result = apply_assignment_mapping(BitVector(0x12345678, 32), SPECIFICATION)
    assert result.vector.width == 32
    assert result.vector.value == 0x78102345
    assert len(result.rows) == 4


def test_mapping_supports_context_sized_constant() -> None:
    result = apply_assignment_mapping(
        BitVector(0xA, 4),
        "output[7:4] = input[3:0]\noutput[3:0] = '1",
    )
    assert result.vector.value == 0xAF


def test_mapping_rejects_gaps() -> None:
    with pytest.raises(MappingError, match="未赋值"):
        apply_assignment_mapping(BitVector(0xA, 4), "output[7:4] = input[3:0]")


def test_mapping_rejects_overlap() -> None:
    with pytest.raises(MappingError, match="重叠"):
        apply_assignment_mapping(
            BitVector(0xA, 4),
            "output[3:0] = input[3:0]\noutput[2:0] = input[2:0]",
        )


def test_pipeline_keeps_intermediate_results() -> None:
    result = run_pipeline(
        BitVector(0x12345678, 32),
        [
            {"type": "reverse_units", "unit_bits": 8},
            {"type": "extract", "msb": 23, "lsb": 8},
        ],
    )
    assert result.final.value == 0x5634
    assert result.final.width == 16
    assert [stage.output_vector.value for stage in result.stages] == [0x78563412, 0x5634]


def test_single_bit_mapping_expressions() -> None:
    result = apply_assignment_mapping(
        BitVector(0b10110010, 8),
        """
        output[3] = input[0]
        output[2] = ~input[1]
        output[1] = input[7] ^ input[6]
        output[0] = ^input[3:0]
        """,
    )
    assert result.vector.value == 0b0011
    assert [(item.output_bit, item.value) for item in result.bits] == [
        (3, 0),
        (2, 0),
        (1, 1),
        (0, 1),
    ]


def test_vector_mapping_expression() -> None:
    result = apply_assignment_mapping(
        BitVector(0xA55A, 16),
        "output[7:0] = input[15:8] ^ input[7:0]",
    )
    assert result.vector.value == 0xFF


def test_extended_pipeline_operations() -> None:
    result = run_pipeline(
        BitVector(0xA5, 8),
        [
            {"type": "binary", "operator": "XOR", "operand": "8'hFF"},
            {"type": "rotate", "direction": "left", "count": 1},
            {"type": "bit_edit", "bit_index": 0, "action": "set"},
            {"type": "append_parity", "mode": "even", "position": "lsb"},
        ],
    )
    assert result.final.width == 9
    assert result.final.value == 0x16B


def test_pipeline_group_reduce_changes_width() -> None:
    result = run_pipeline(
        BitVector(0x12345678, 32),
        [{"type": "group_reduce", "operator": "XOR", "group_bits": 2, "direction": "lsb"}],
    )
    assert result.final.width == 16
    assert result.final.value == 0x52FA
    assert "每 2 bit 分组归约 XOR" in result.stages[0].description
