from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import DataToolError


def _safe_name(name: str) -> str:
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    if not normalized:
        raise DataToolError("模板名称不能为空")
    return normalized[:80]


def list_templates(directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    return sorted(path.stem for path in directory.glob("*.json"))


def save_template(directory: Path, name: str, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_name(name)
    path = directory / f"{safe_name}.json"
    document = {"version": 1, "name": name.strip(), **payload}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_template(directory: Path, file_stem: str) -> dict[str, Any]:
    safe_name = _safe_name(file_stem)
    path = directory / f"{safe_name}.json"
    if not path.is_file():
        raise DataToolError(f"模板不存在：{file_stem}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataToolError(f"模板文件无法读取：{exc}") from exc
    if document.get("version") != 1 or not isinstance(document.get("steps"), list):
        raise DataToolError("模板版本或内容格式不正确")
    return document
