from __future__ import annotations

import json
import re
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import DataToolError
from .validation import integer, validate_steps


def _safe_name(name: str) -> str:
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    if not normalized:
        raise DataToolError("模板名称不能为空")
    if normalized.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        normalized = f"template_{normalized}"
    return normalized[:80]


def list_templates(directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    return sorted(path.stem for path in directory.glob("*.json"))


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_template(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
        raise DataToolError("模板版本或内容格式不正确")
    result = dict(document)
    result["steps"] = validate_steps(document.get("steps"))
    defaults = document.get("input_defaults", {})
    if not isinstance(defaults, dict):
        raise DataToolError("input_defaults 必须是对象")
    if not isinstance(defaults.get("format_hint", "auto"), str) or defaults.get("format_hint", "auto") not in {"auto", "hex", "bin", "dec", "bytes"}:
        raise DataToolError("模板中的输入格式不正确")
    width = integer(0 if defaults.get("width") is None else defaults.get("width", 0), "输入位宽")
    if width > 4096:
        raise DataToolError("界面输入位宽最多为 4096 bit")
    if not isinstance(defaults.get("signed_mode", "自动"), str) or defaults.get("signed_mode", "自动") not in {"自动", "无符号", "有符号"}:
        raise DataToolError("模板中的数据类型不正确")
    if not isinstance(document.get("sample_input", ""), str):
        raise DataToolError("示例输入必须是文本")
    result["input_defaults"] = {**defaults, "width": width}
    return result


def save_template(directory: Path, name: str, payload: dict[str, Any], overwrite: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_name(name)
    path = directory / f"{safe_name}.json"
    document = validate_template({**payload, "version": 1, "name": name.strip()})
    if path.exists() and not overwrite:
        raise DataToolError("同名模板已存在；请改名，或勾选允许覆盖")
    try:
        atomic_write(path, document)
    except OSError as exc:
        raise DataToolError(f"模板保存失败：{exc}") from exc
    return path


def load_template(directory: Path, file_stem: str) -> dict[str, Any]:
    safe_name = _safe_name(file_stem)
    path = directory / f"{safe_name}.json"
    if not path.is_file():
        raise DataToolError(f"模板不存在：{file_stem}")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataToolError(f"模板文件无法读取：{exc}") from exc
    return validate_template(document)
