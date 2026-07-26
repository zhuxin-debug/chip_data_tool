import pytest

from core import BitVector, OperationError
from core.operations import (
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
)


def test_reverse_all_bits() -> None:
    assert reverse_all_bits(BitVector(0b11010000, 8)).value == 0b00001011


def test_reverse_byte_order() -> None:
    assert reverse_unit_order(BitVector(0x12345678, 32), 8).value == 0x78563412


def test_reverse_nibble_order() -> None:
    assert reverse_unit_order(BitVector(0xABCD, 16), 4).value == 0xDCBA


def test_reverse_bits_inside_each_byte() -> None:
    assert reverse_bits_in_units(BitVector(0x12, 8), 8).value == 0x48


def test_extract() -> None:
    result = extract_bits(BitVector(0x12345678, 32), 23, 8)
    assert result.width == 16
    assert result.value == 0x3456


def test_unit_must_divide_width() -> None:
    with pytest.raises(OperationError, match="不能按 8 bit"):
        reverse_unit_order(BitVector(0xFFF, 12), 8)


def test_binary_logic_and_arithmetic_wrap() -> None:
    source = BitVector(0xA5, 8)
    assert binary_operation(source, "XOR", "8'hFF").value == 0x5A
    assert binary_operation(source, "AND", "8'h0F").value == 0x05
    assert binary_operation(BitVector(0xFF, 8), "ADD", "8'd1").value == 0x00


def test_not_shift_rotate_and_bit_edit() -> None:
    source = BitVector(0x81, 8)
    assert invert_bits(source).value == 0x7E
    assert shift_bits(source, "right", 1).value == 0x40
    assert shift_bits(BitVector(0x80, 8, True), "arithmetic_right", 1).value == 0xC0
    assert rotate_bits(source, "left", 1).value == 0x03
    assert rotate_bits(source, "right", 1).value == 0xC0
    assert edit_bit(source, 1, "set").value == 0x83
    assert edit_bit(source, 0, "clear").value == 0x80
    assert edit_bit(source, 7, "toggle").value == 0x01


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("AND", 0b1010),
        ("OR", 0b1011),
        ("XOR", 0b1011),
        ("XNOR", 0b1010),
    ],
)
def test_selected_bit_logic(operator: str, expected: int) -> None:
    result = bit_logic_operation(
        BitVector(0b1010, 4),
        left_bit=3,
        operator=operator,
        right_bit=2,
        target_bit=0,
    )
    assert result.value == expected


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("AND", 0x4), ("OR", 0xD), ("XOR", 0x9), ("XNOR", 0x6)],
)
def test_group_reduce_operators(operator: str, expected: int) -> None:
    result = group_reduce(BitVector(0xB2, 8), operator, group_bits=2)
    assert result.width == 4
    assert result.value == expected


def test_pairwise_xor_example() -> None:
    result = group_reduce(BitVector(0x12345678, 32), "XOR", group_bits=2)
    assert result.to_sv_hex() == "16'h52FA"


def test_group_reduce_msb_first_and_invalid_width() -> None:
    assert group_reduce(BitVector(0xA4, 8), "XOR", 2, "lsb").value == 0xE
    assert group_reduce(BitVector(0xA4, 8), "XOR", 2, "msb").value == 0x7
    with pytest.raises(OperationError, match="不能按 2 bit"):
        group_reduce(BitVector(0x1F, 5), "XOR", 2)
