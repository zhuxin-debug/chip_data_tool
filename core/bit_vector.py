from __future__ import annotations

from dataclasses import dataclass


def _group_from_right(text: str, size: int, separator: str = "_") -> str:
    groups: list[str] = []
    while text:
        groups.append(text[-size:])
        text = text[:-size]
    return separator.join(reversed(groups))


@dataclass(frozen=True, slots=True)
class BitVector:
    """An immutable fixed-width bit vector.

    ``value`` always stores the raw unsigned bits. ``signed`` only controls how
    the same bits are interpreted; it never changes the stored bit pattern.
    """

    value: int
    width: int
    signed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.width, int) or self.width <= 0:
            raise ValueError("数据位宽必须是大于 0 的整数")
        if not isinstance(self.value, int):
            raise ValueError("数据值必须是整数")
        if self.value < 0 or self.value > self.mask:
            raise ValueError(f"数据 0x{self.value:X} 无法放入 {self.width} bit")

    @property
    def mask(self) -> int:
        return (1 << self.width) - 1

    @property
    def unsigned_value(self) -> int:
        return self.value

    @property
    def twos_complement_value(self) -> int:
        sign_bit = 1 << (self.width - 1)
        return self.value - (1 << self.width) if self.value & sign_bit else self.value

    @property
    def interpreted_value(self) -> int:
        return self.twos_complement_value if self.signed else self.value

    def with_signed(self, signed: bool) -> "BitVector":
        return BitVector(self.value, self.width, signed)

    def slice(self, msb: int, lsb: int) -> "BitVector":
        if lsb < 0 or msb < lsb or msb >= self.width:
            raise ValueError(
                f"字段范围 [{msb}:{lsb}] 超出当前数据范围 [{self.width - 1}:0]"
            )
        width = msb - lsb + 1
        return BitVector((self.value >> lsb) & ((1 << width) - 1), width)

    def hex_digits(self, grouped: bool = True) -> str:
        digits = max(1, (self.width + 3) // 4)
        text = f"{self.value:0{digits}X}"
        return _group_from_right(text, 4) if grouped else text

    def binary_digits(self, grouped: bool = True) -> str:
        text = f"{self.value:0{self.width}b}"
        return _group_from_right(text, 4) if grouped else text

    def to_hex(self) -> str:
        return f"0x{self.hex_digits()}"

    def to_binary(self) -> str:
        return f"0b{self.binary_digits()}"

    def to_sv_hex(self) -> str:
        signed_marker = "s" if self.signed else ""
        return f"{self.width}'{signed_marker}h{self.hex_digits()}"

    def to_sv_binary(self) -> str:
        signed_marker = "s" if self.signed else ""
        return f"{self.width}'{signed_marker}b{self.binary_digits()}"

    def to_bytes(self) -> str:
        if self.width % 8:
            return "位宽不是 8 的整数倍"
        byte_count = self.width // 8
        return " ".join(
            f"{(self.value >> shift) & 0xFF:02X}"
            for shift in range((byte_count - 1) * 8, -1, -8)
        )
