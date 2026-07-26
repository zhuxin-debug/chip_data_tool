from core import (
    CRC_PRESETS,
    BitVector,
    calculate_crc,
    compare_actual_expected,
    generate_systemverilog,
)


def test_expected_pattern_with_dont_care_bits() -> None:
    result = compare_actual_expected(BitVector(0x12AB, 16), "16'h12??")
    assert result.matches
    assert result.ignored_count == 8


def test_comparison_finds_different_bits() -> None:
    result = compare_actual_expected(BitVector(0b1010, 4), "4'b1001")
    assert result.diff_mask == 0b0011
    assert result.different_count == 2
    assert result.first_difference_msb == 1


def test_standard_crc_check_values() -> None:
    data = b"123456789"
    vector = BitVector(int.from_bytes(data, "big"), len(data) * 8)
    assert calculate_crc(vector, CRC_PRESETS["CRC-8"]).value == 0xF4
    assert calculate_crc(vector, CRC_PRESETS["CRC-16/CCITT-FALSE"]).value == 0x29B1
    assert calculate_crc(vector, CRC_PRESETS["CRC-32/ISO-HDLC"]).value == 0xCBF43926


def test_systemverilog_generation() -> None:
    code = generate_systemverilog(
        BitVector(0x12, 8),
        [
            {"type": "binary", "operator": "XOR", "operand": "8'hFF"},
            {"type": "bit_edit", "bit_index": 0, "action": "set"},
            {
                "type": "bit_logic",
                "left_bit": 7,
                "operator": "XOR",
                "right_bit": 6,
                "target_bit": 1,
            },
        ],
        "convert_data",
    )
    assert "function automatic logic [7:0] convert_data" in code
    assert "step_1 = input_data ^ 8'hFF;" in code
    assert "step_2[0] = 1'b1;" in code
    assert "step_3[1] = step_2[7] ^ step_2[6];" in code


def test_group_reduce_systemverilog_generation() -> None:
    code = generate_systemverilog(
        BitVector(0x12345678, 32),
        [{"type": "group_reduce", "operator": "XOR", "group_bits": 2, "direction": "lsb"}],
        "pairwise_xor",
    )
    assert "function automatic logic [15:0] pairwise_xor" in code
    assert "step_1[i_1] = ^input_data[i_1*2 +: 2];" in code
