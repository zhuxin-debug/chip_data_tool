from __future__ import annotations

from dataclasses import dataclass

from .bit_vector import BitVector
from .errors import OperationError


@dataclass(frozen=True, slots=True)
class CRCPreset:
    name: str
    width: int
    polynomial: int
    initial: int
    reflect_input: bool
    reflect_output: bool
    xor_output: int


CRC_PRESETS: dict[str, CRCPreset] = {
    "CRC-8": CRCPreset("CRC-8", 8, 0x07, 0x00, False, False, 0x00),
    "CRC-16/CCITT-FALSE": CRCPreset(
        "CRC-16/CCITT-FALSE", 16, 0x1021, 0xFFFF, False, False, 0x0000
    ),
    "CRC-32/ISO-HDLC": CRCPreset(
        "CRC-32/ISO-HDLC", 32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF
    ),
}


def _reflect(value: int, width: int) -> int:
    return int(f"{value:0{width}b}"[::-1], 2)


def calculate_parity(vector: BitVector, mode: str = "even") -> int:
    xor_reduction = vector.value.bit_count() & 1
    normalized = mode.lower()
    if normalized == "even":
        return xor_reduction
    if normalized == "odd":
        return xor_reduction ^ 1
    raise OperationError(f"不支持的 parity 类型：{mode}")


def append_parity(vector: BitVector, mode: str = "even", position: str = "lsb") -> BitVector:
    parity = calculate_parity(vector, mode)
    normalized = position.lower()
    if normalized == "lsb":
        value = (vector.value << 1) | parity
    elif normalized == "msb":
        value = (parity << vector.width) | vector.value
    else:
        raise OperationError(f"不支持的 parity 位置：{position}")
    return BitVector(value, vector.width + 1)


def calculate_crc(vector: BitVector, preset: CRCPreset, byte_order: str = "big") -> BitVector:
    """Calculate a CRC with explicit byte order (reflection is independent)."""

    if vector.width % 8:
        raise OperationError("CRC 输入位宽必须是 8 的整数倍")
    if byte_order not in {"big", "little"}:
        raise OperationError("字节顺序必须为 big 或 little")
    if type(preset.width) is not int or not 8 <= preset.width <= 64:
        raise OperationError("CRC 位宽必须为 8～64 的整数")
    for name, value in {"poly": preset.polynomial, "init": preset.initial, "xorout": preset.xor_output}.items():
        if type(value) is not int or not 0 <= value < 1 << preset.width:
            raise OperationError(f"CRC {name} 超出 {preset.width} bit 范围")
    if not preset.polynomial:
        raise OperationError("CRC 多项式不能为 0")
    data = vector.value.to_bytes(vector.width // 8, byteorder=byte_order)
    width = preset.width
    mask = (1 << width) - 1
    crc = preset.initial & mask

    if preset.reflect_input:
        reflected_polynomial = _reflect(preset.polynomial, width)
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ reflected_polynomial if crc & 1 else crc >> 1
                crc &= mask
    else:
        top_bit = 1 << (width - 1)
        for byte in data:
            crc ^= byte << (width - 8)
            for _ in range(8):
                crc = ((crc << 1) ^ preset.polynomial) if crc & top_bit else crc << 1
                crc &= mask

    if preset.reflect_output != preset.reflect_input:
        crc = _reflect(crc, width)
    crc ^= preset.xor_output
    return BitVector(crc & mask, width)
