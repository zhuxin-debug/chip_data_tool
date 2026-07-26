import pytest

from core import ParseError, parse_value


def test_parse_systemverilog_hex() -> None:
    parsed = parse_value("32'h1234_5678")
    assert parsed.vector.width == 32
    assert parsed.vector.value == 0x12345678
    assert parsed.vector.to_sv_hex() == "32'h1234_5678"


def test_parse_signed_systemverilog_pattern() -> None:
    parsed = parse_value("8'shFF")
    assert parsed.vector.signed is True
    assert parsed.vector.twos_complement_value == -1


def test_parse_negative_decimal() -> None:
    parsed = parse_value("-128", width=8, signed=True)
    assert parsed.vector.value == 0x80
    assert parsed.vector.interpreted_value == -128


def test_parse_byte_stream() -> None:
    parsed = parse_value("12 34 56 78", format_hint="bytes")
    assert parsed.vector.width == 32
    assert parsed.vector.value == 0x12345678
    assert parsed.vector.to_bytes() == "12 34 56 78"


def test_plain_digits_are_decimal_in_auto_mode() -> None:
    parsed = parse_value("1010")
    assert parsed.detected_format == "十进制"
    assert parsed.vector.value == 1010


def test_unknown_bits_are_rejected() -> None:
    with pytest.raises(ParseError, match="X、Z"):
        parse_value("8'hxF")


def test_width_overflow_is_rejected() -> None:
    with pytest.raises(ParseError, match="超出 8 bit"):
        parse_value("0x1FF", width=8)


def test_declared_and_selected_width_conflict() -> None:
    with pytest.raises(ParseError, match="输入声明为 32 bit"):
        parse_value("32'h12", width=16)
