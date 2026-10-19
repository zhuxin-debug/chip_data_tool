"""Portable, validated workspaces and reproducible batch configuration IDs."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from .errors import DataToolError
from .templates import validate_template


DEFAULTS = {
    "steps": [], "raw_value": "32'h1234_5678", "input_format": "自动识别",
    "input_width": 0, "signed_mode": "自动",
    "batch_text": "32'h1234_5678\n32'hAABB_CCDD\n32'h0000_1234",
    "compare_expected": "32'h1234_5678", "compare_actual": "32'h1234_5678",
    "actual_source_mode": "使用当前转换结果", "checksum_source_mode": "使用当前转换结果",
    "checksum_text": "72'h3132_3334_3536_3738_39", "crc_order": "高字节在前",
    "crc_preset": "CRC-8", "function_name": "transform_data",
    "custom_crc_width": 16, "custom_crc_poly": "0x1021", "custom_crc_init": "0xFFFF",
    "custom_crc_xor": "0x0000", "custom_crc_refin": False, "custom_crc_refout": False,
}
FORMATS = {"自动识别": "auto", "SystemVerilog / 十六进制": "hex", "二进制": "bin", "十进制": "dec", "字节流（左侧为高字节）": "bytes"}


def snapshot(state: Any) -> dict[str, Any]:
    return {key: deepcopy(state.get(key, value)) for key, value in DEFAULTS.items()}


def validate_workspace(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("kind") != "chip-data-workspace" or type(document.get("version")) is not int or document["version"] != 1:
        raise DataToolError("不是受支持的工作现场文件（version=1）")
    state = document.get("state")
    if not isinstance(state, dict):
        raise DataToolError("工作现场缺少 state 对象")
    result = snapshot(state)
    if not isinstance(result["input_format"], str) or result["input_format"] not in FORMATS:
        raise DataToolError("工作现场中的输入格式不正确")
    for key, default in DEFAULTS.items():
        if isinstance(default, str) and not isinstance(result[key], str):
            raise DataToolError(f"工作现场中的 {key} 必须是文本")
        if isinstance(default, bool) and not isinstance(result[key], bool):
            raise DataToolError(f"工作现场中的 {key} 必须是布尔值")
    for key, options in {
        "actual_source_mode": ["使用当前转换结果", "使用原始输入", "手动输入 Actual"],
        "checksum_source_mode": ["使用当前转换结果", "使用原始输入", "手动输入"],
        "crc_order": ["高字节在前", "低字节在前"],
        "crc_preset": ["CRC-8", "CRC-16/CCITT-FALSE", "CRC-32/ISO-HDLC", "自定义"],
    }.items():
        if result[key] not in options:
            raise DataToolError(f"工作现场中的 {key} 选项不正确")
    if type(result["custom_crc_width"]) is not int or not 8 <= result["custom_crc_width"] <= 64:
        raise DataToolError("自定义 CRC 位宽必须为 8～64 的整数")
    template = validate_template({"version": 1, "steps": result["steps"], "input_defaults": {
        "format_hint": FORMATS[result["input_format"]], "width": result["input_width"], "signed_mode": result["signed_mode"]}})
    result["steps"] = template["steps"]
    result["input_width"] = template["input_defaults"]["width"]
    return result


def workspace_document(state: Any) -> dict[str, Any]:
    return {"kind": "chip-data-workspace", "version": 1, "state": snapshot(state)}


def fingerprint(document: Any) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
