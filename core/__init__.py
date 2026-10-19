"""Chip data transformation core API."""

from .bit_vector import BitVector
from .checksum import CRC_PRESETS, CRCPreset, append_parity, calculate_crc, calculate_parity
from .codegen import generate_systemverilog
from .comparison import ComparisonResult, compare_actual_expected, parse_expected_pattern
from .errors import DataToolError, MappingError, OperationError, ParseError
from .mapping import MappingBit, MappingResult, apply_assignment_mapping
from .operations import (
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
    resize_bits,
)
from .parser import ParsedValue, parse_value
from .pipeline import PipelineResult, describe_step, run_pipeline

__all__ = [
    "BitVector",
    "CRC_PRESETS",
    "CRCPreset",
    "ComparisonResult",
    "DataToolError",
    "MappingError",
    "MappingBit",
    "MappingResult",
    "OperationError",
    "ParseError",
    "ParsedValue",
    "PipelineResult",
    "apply_assignment_mapping",
    "append_parity",
    "bit_logic_operation",
    "binary_operation",
    "calculate_crc",
    "calculate_parity",
    "compare_actual_expected",
    "describe_step",
    "edit_bit",
    "extract_bits",
    "generate_systemverilog",
    "group_reduce",
    "invert_bits",
    "parse_value",
    "parse_expected_pattern",
    "reverse_all_bits",
    "reverse_bits_in_units",
    "reverse_unit_order",
    "rotate_bits",
    "run_pipeline",
    "shift_bits",
    "resize_bits",
]
