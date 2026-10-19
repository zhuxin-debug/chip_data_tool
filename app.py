from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import streamlit as st

from core import (
    CRC_PRESETS,
    BitVector,
    ComparisonResult,
    DataToolError,
    PipelineResult,
    calculate_crc,
    calculate_parity,
    compare_actual_expected,
    describe_step,
    generate_systemverilog,
    parse_value,
    run_pipeline,
)
from core.templates import list_templates, load_template, save_template
from core.validation import validate_steps
from core.workspace import FORMATS, fingerprint, validate_workspace, workspace_document
from core.provenance import mapping_html
from core.checksum import CRCPreset
from core.codegen import _safe_identifier
import ui_state


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_DIR / "configs"

FORMAT_OPTIONS = {
    "自动识别": "auto",
    "SystemVerilog / 十六进制": "hex",
    "二进制": "bin",
    "十进制": "dec",
    "字节流（左侧为高字节）": "bytes",
}
SIGNED_OPTIONS: dict[str, bool | None] = {
    "自动": None,
    "无符号": False,
    "有符号": True,
}
OPERATION_OPTIONS = {
    "整体 bit 反向": "reverse_bits",
    "按单元反向排列": "reverse_units",
    "每个单元内部 bit 反向": "reverse_bits_in_units",
    "提取字段 [MSB:LSB]": "extract",
    "字段 / 逐 bit 映射": "mapping",
    "整段数据 AND / OR / XOR / XNOR / 加减": "binary",
    "两个指定 bit 做 AND / OR / XOR / XNOR": "bit_logic",
    "按 N bit 分组归约 AND / OR / XOR / XNOR": "group_reduce",
    "按位取反 NOT": "not",
    "逻辑 / 算术移位": "shift",
    "循环移位": "rotate",
    "设置 / 清除 / 翻转指定 bit": "bit_edit",
    "追加 Parity bit": "append_parity",
    "位宽转换：补零 / 符号扩展 / 截断": "resize",
}
DEFAULT_MAPPING = """output[31:24] = input[7:0]
output[23:20] = input[31:28]
output[19:16] = 4'h0
output[15:0]  = input[27:12]"""
BIT_MAPPING_EXAMPLE = """output[3] = input[0]
output[2] = ~input[1]
output[1] = input[7] ^ input[6]
output[0] = ^input[3:0]"""


def _init_state() -> None:
    ui_state.initialize()
    ui_state.checkpoint()


def _install_styles() -> None:
    st.markdown(
        """
<style>
.bit-grid { display:flex; flex-wrap:wrap; gap:.75rem; margin:.5rem 0 1rem; }
.bit-byte { border:1px solid rgba(128,128,128,.28); border-radius:.55rem; padding:.4rem; }
.bit-byte-title { text-align:center; font-size:.72rem; opacity:.7; margin-bottom:.3rem; }
.bit-cells { display:flex; gap:.18rem; }
.bit-cell { min-width:2.15rem; text-align:center; border-radius:.35rem; padding:.25rem .2rem; }
.bit-cell .index { display:block; font-size:.62rem; opacity:.72; }
.bit-cell .value { display:block; font:700 1rem monospace; }
.bit-one { background:rgba(46,160,67,.22); color:#2ea043; }
.bit-zero { background:rgba(110,118,129,.16); }
.bit-diff { background:rgba(248,81,73,.25); color:#f85149; outline:1px solid #f85149; }
.bit-ignore { background:rgba(210,153,34,.18); color:#d29922; }
</style>
""",
        unsafe_allow_html=True,
    )


def _short(text: str, limit: int = 72) -> str:
    if len(text) <= limit:
        return text
    keep = (limit - 3) // 2
    return f"{text[:keep]}...{text[-keep:]}"


def _vector_rows(vector: BitVector) -> list[dict[str, str]]:
    return [
        {"格式": "SystemVerilog Hex", "结果": vector.to_sv_hex()},
        {"格式": "Hex", "结果": vector.to_hex()},
        {"格式": "Binary", "结果": vector.to_binary()},
        {"格式": "Unsigned Decimal", "结果": str(vector.unsigned_value)},
        {"格式": "Signed（二进制补码）", "结果": str(vector.twos_complement_value)},
        {"格式": "Bytes（MSB → LSB）", "结果": vector.to_bytes()},
    ]


def _vector_text(vector: BitVector) -> str:
    return "\n".join(
        [
            f"SystemVerilog: {vector.to_sv_hex()}",
            f"Hex:           {vector.to_hex()}",
            f"Binary:        {vector.to_binary()}",
            f"Unsigned:      {vector.unsigned_value}",
            f"Signed:        {vector.twos_complement_value}",
            f"Bytes:         {vector.to_bytes()}",
        ]
    )


def _render_bit_grid(
    vector: BitVector,
    title: str,
    statuses: dict[int, str] | None = None,
    expected: dict[int, str] | None = None,
) -> None:
    st.markdown(f"**{title}** · `{vector.width} bit` · bit 顺序 `MSB → LSB`")
    page_key = f"bit_page_{title}"
    pages = list(range((vector.width + 63) // 64))
    if st.session_state.get(page_key, 0) not in pages:
        st.session_state[page_key] = 0
    page = st.selectbox("显示位范围", pages, key=page_key,
                        format_func=lambda p: f"bit[{min(vector.width - 1, p * 64 + 63)}:{p * 64}]") if len(pages) > 1 else 0
    highest = min(vector.width - 1, page * 64 + 63)
    lowest = page * 64
    groups: list[str] = []
    group_high = highest
    while group_high >= lowest:
        group_low = max(lowest, group_high - 7)
        cells: list[str] = []
        for bit in range(group_high, group_low - 1, -1):
            value = (vector.value >> bit) & 1
            status = (statuses or {}).get(bit, "")
            css_class = {
                "不同": "bit-diff",
                "忽略": "bit-ignore",
            }.get(status, "bit-one" if value else "bit-zero")
            display_value = (expected or {}).get(bit, str(value))
            cells.append(
                f'<div class="bit-cell {css_class}" title="bit[{bit}]">'
                f'<span class="index">{bit}</span><span class="value">{display_value}</span></div>'
            )
        label = f"bit[{group_high}:{group_low}]" if group_high != group_low else f"bit[{group_high}]"
        groups.append(
            f'<div class="bit-byte"><div class="bit-byte-title">{label}</div>'
            f'<div class="bit-cells">{"".join(cells)}</div></div>'
        )
        group_high = group_low - 1
    st.markdown(f'<div class="bit-grid">{"".join(groups)}</div>', unsafe_allow_html=True)
    if vector.width > 64:
        st.caption("可切换查看全部位范围；完整数据始终参与计算。")


def _toggle_input_bit(value: int, width: int, signed: bool, bit: int) -> None:
    toggled = BitVector(value ^ (1 << bit), width, signed)
    st.session_state.raw_value = toggled.to_sv_hex()


def _render_input_bit_editor(vector: BitVector) -> None:
    st.markdown(
        f"**输入 bit 视图** · `{vector.width} bit` · bit 顺序 `MSB → LSB` · 点击切换 `0/1`"
    )
    pages = list(range((vector.width + 63) // 64))
    if st.session_state.get("input_bit_page", 0) not in pages:
        st.session_state.input_bit_page = 0
    page = st.selectbox("输入位范围", pages, key="input_bit_page",
                        format_func=lambda p: f"bit[{min(vector.width - 1, p * 64 + 63)}:{p * 64}]") if len(pages) > 1 else 0
    group_high = min(vector.width - 1, page * 64 + 63)
    while group_high >= page * 64:
        group_low = max(page * 64, group_high - 7)
        st.caption(
            f"bit[{group_high}:{group_low}]" if group_high != group_low else f"bit[{group_high}]"
        )
        bit_numbers = list(range(group_high, group_low - 1, -1))
        columns = st.columns(len(bit_numbers))
        for column, bit in zip(columns, bit_numbers):
            value = (vector.value >> bit) & 1
            column.button(
                f"{bit}: {value}",
                key=f"input_bit_toggle_{vector.width}_{bit}",
                type="primary" if value else "secondary",
                help=f"点击把 bit[{bit}] 从 {value} 切换为 {value ^ 1}",
                width="stretch",
                on_click=_toggle_input_bit,
                args=(vector.value, vector.width, vector.signed, bit),
            )
        group_high = group_low - 1


def _render_template_sidebar() -> None:
    with st.sidebar:
        st.header("工作现场")
        if st.session_state.get("_restore_message"):
            st.caption(st.session_state.pop("_restore_message"))
        undo, redo = st.columns(2)
        undo.button("撤销", on_click=ui_state.undo, disabled=len(st.session_state._history) < 2)
        redo.button("重做", on_click=ui_state.redo, disabled=not st.session_state._future)
        st.checkbox("自动保存工作现场到本机", value=True, key="autosave")
        st.caption("自动恢复输入、流水线、批量数据和对比/校验设置；保留最近 40 次撤销。")
        st.download_button("导出工作现场 JSON", data=json.dumps(workspace_document(st.session_state), ensure_ascii=False, indent=2),
                           file_name="chip_data_workspace.json", mime="application/json")
        uploaded = st.file_uploader("导入工作现场", type=["json"], key="workspace_import")
        if st.button("恢复导入的工作现场", disabled=uploaded is None):
            try:
                state = validate_workspace(json.loads(uploaded.getvalue().decode("utf-8-sig")))
                ui_state.restore(state)
                ui_state.checkpoint()
                st.rerun()
            except (DataToolError, ValueError, UnicodeError) as exc:
                st.error(f"导入失败，当前工作未更改：{exc}")
        st.divider()
        st.header("转换模板")
        templates = list_templates(CONFIG_DIR)
        if templates:
            selected = st.selectbox("已有模板", templates)
            if st.button("加载模板", width="stretch"):
                try:
                    document = load_template(CONFIG_DIR, selected)
                    defaults = document.get("input_defaults", {})
                    st.session_state.steps = document["steps"]
                    if document.get("sample_input"):
                        st.session_state.raw_value = str(document["sample_input"])
                    st.session_state.input_format = next(
                        (
                            label
                            for label, value in FORMAT_OPTIONS.items()
                            if value == defaults.get("format_hint", "auto")
                        ),
                        "自动识别",
                    )
                    st.session_state.input_width = int(defaults.get("width") or 0)
                    signed_mode = defaults.get("signed_mode", "自动")
                    st.session_state.signed_mode = signed_mode if signed_mode in SIGNED_OPTIONS else "自动"
                    st.session_state._editing = None
                    st.session_state._editor_revision += 1
                    ui_state.checkpoint()
                    st.success(f"已加载：{selected}")
                    st.rerun()
                except DataToolError as exc:
                    st.error(str(exc))
        else:
            st.caption("还没有模板")

        st.divider()
        template_name = st.text_input("新模板名称", placeholder="例如 PCIe_Header")
        overwrite = st.checkbox("允许覆盖同名模板", value=False)
        if st.button("保存当前规则", width="stretch"):
            try:
                path = save_template(
                    CONFIG_DIR,
                    template_name,
                    {
                        "input_defaults": {
                            "format_hint": FORMAT_OPTIONS[st.session_state.input_format],
                            "width": int(st.session_state.input_width),
                            "signed_mode": st.session_state.signed_mode,
                        },
                        "steps": st.session_state.steps,
                        "sample_input": st.session_state.raw_value,
                    },
                    overwrite=overwrite,
                )
                st.success(f"已保存：{path.stem}")
            except DataToolError as exc:
                st.error(str(exc))

        st.divider()
        st.caption("数据和模板均保存在本机，不会上传。")


def _build_step(initial: dict | None = None, prefix: str = "new") -> dict[str, Any]:
    initial = initial or {}
    if initial:
        operation_type = initial["type"]
        st.caption(next(label for label, kind in OPERATION_OPTIONS.items() if kind == operation_type))
    else:
        label = st.selectbox("操作类型", list(OPERATION_OPTIONS), key=f"{prefix}_type")
        operation_type = OPERATION_OPTIONS[label]
    step: dict[str, Any] = {"type": operation_type}
    if "enabled" in initial:
        step["enabled"] = initial["enabled"]
    def number(field: str, label: str, default: int, minimum: int = 0) -> None:
        step[field] = int(st.number_input(label, min_value=minimum,
            value=int(initial.get(field, default)), step=1, key=f"{prefix}_{operation_type}_{field}"))
    def choice(field: str, label: str, options: dict[str, str], default: str) -> None:
        values = list(options.values())
        step[field] = st.selectbox(label, values, index=values.index(initial.get(field, default)),
            format_func=lambda value: next(label for label, code in options.items() if code == value),
            key=f"{prefix}_{operation_type}_{field}")
    def text(field: str, label: str, default: str, area: bool = False) -> None:
        widget = st.text_area if area else st.text_input
        step[field] = widget(label, value=initial.get(field, default), key=f"{prefix}_{operation_type}_{field}")
    if operation_type in {"reverse_units", "reverse_bits_in_units"}:
        number("unit_bits", "每单元位数", 8, 1)
    elif operation_type == "extract":
        number("msb", "MSB", 23)
        number("lsb", "LSB", 8)
    elif operation_type == "mapping":
        text("specification", "映射规则", DEFAULT_MAPPING, True)
        number("output_width", "输出位宽（0 为自动）", 0)
        st.caption("支持 input[7:0]、~input[3]、input[7] ^ input[2]、^input[7:0]。二元运算符两侧请留空格。")
    elif operation_type in {"binary", "bit_logic", "group_reduce"}:
        operators = ["XOR", "AND", "OR", "XNOR"] + (["ADD", "SUB"] if operation_type == "binary" else [])
        choice("operator", "运算符", {x: x for x in operators}, "XOR")
        if operation_type == "binary":
            text("operand", "第二运算数", "8'hFF")
            st.caption("可填定宽常量或 input[7:0]；短操作数补零，加减按当前位宽回绕。")
        elif operation_type == "bit_logic":
            number("left_bit", "左 bit", 7)
            number("right_bit", "右 bit", 6)
            number("target_bit", "写入目标 bit", 0)
        else:
            number("group_bits", "每组位数", 2, 1)
            choice("direction", "分组输出顺序", {"从 LSB 开始": "lsb", "从 MSB 开始": "msb"}, "lsb")
    elif operation_type in {"shift", "rotate"}:
        options = {"左移": "left", "右移": "right"}
        if operation_type == "shift":
            options["算术右移"] = "arithmetic_right"
        choice("direction", "方向", options, "left")
        number("count", "移动位数", 1)
    elif operation_type == "bit_edit":
        number("bit_index", "bit 编号", 0)
        choice("action", "操作", {"置为 1": "set", "清为 0": "clear", "翻转": "toggle"}, "toggle")
    elif operation_type == "append_parity":
        choice("mode", "Parity 类型", {"偶校验": "even", "奇校验": "odd"}, "even")
        choice("position", "追加位置", {"LSB": "lsb", "MSB": "msb"}, "lsb")
    elif operation_type == "resize":
        number("width", "目标位宽", 32, 1)
        choice("mode", "位宽处理方式", {"补零扩展": "zero", "符号扩展（复制最高位）": "sign", "截断（保留低位）": "truncate"}, "zero")
    return step


def _replace_steps(steps: list[dict[str, Any]]) -> None:
    try:
        st.session_state.steps = validate_steps(steps)
        ui_state.checkpoint()
        st.session_state._editing = None
        st.session_state._editor_revision += 1
        st.rerun()
    except DataToolError as exc:
        st.error(str(exc))


def _pipeline_action(action: str, index: int = 0, candidate: dict | None = None, prefix: str = "") -> None:
    if action == "edit":
        st.session_state._editing = index
        st.session_state._editor_revision += 1
        return
    if action == "cancel":
        st.session_state._editing = None
        return
    steps = deepcopy(st.session_state.steps)
    if action == "save":
        candidate = deepcopy(candidate)
        for field in candidate:
            key = f"{prefix}_{candidate['type']}_{field}"
            if key in st.session_state:
                candidate[field] = st.session_state[key]
        steps[index] = candidate
    elif action == "toggle":
        steps[index]["enabled"] = not steps[index].get("enabled", True)
    elif action == "copy":
        steps.insert(index + 1, deepcopy(steps[index]))
    elif action == "up":
        steps[index - 1], steps[index] = steps[index], steps[index - 1]
    elif action == "down":
        steps[index + 1], steps[index] = steps[index], steps[index + 1]
    elif action == "delete":
        steps.pop(index)
    elif action == "clear":
        steps = []
    try:
        st.session_state.steps = validate_steps(steps)
        ui_state.checkpoint()
        st.session_state._editing = None
        st.session_state._editor_revision += 1
    except DataToolError as exc:
        st.session_state._pipeline_message = str(exc)


def _render_pipeline_editor() -> None:
    st.subheader("转换流水线")
    if st.session_state.get("_pipeline_message"):
        st.error(st.session_state.pop("_pipeline_message"))
    with st.expander("添加转换步骤", expanded=not st.session_state.steps):
        step = _build_step()
        if st.button("添加到流水线", type="primary"):
            _replace_steps(st.session_state.steps + [step])
    editing = st.session_state._editing
    if editing is not None and editing < len(st.session_state.steps):
        with st.container(border=True):
            st.markdown(f"**编辑第 {editing + 1} 步**")
            prefix = f"edit_{editing}_{st.session_state._editor_revision}"
            candidate = _build_step(st.session_state.steps[editing], prefix)
            save, cancel = st.columns(2)
            save.button("保存修改", type="primary", on_click=_pipeline_action, args=("save", editing, candidate, prefix))
            cancel.button("取消修改", on_click=_pipeline_action, args=("cancel",))
    if not st.session_state.steps:
        st.info("当前没有转换步骤；解析结果将直接作为最终结果。")
        return
    for index, step in enumerate(st.session_state.steps):
        with st.container(border=True):
            enabled = step.get("enabled", True)
            st.write(f"**{index + 1}. {describe_step(step)}**" + (" · 已停用" if not enabled else ""))
            edit, toggle, copy, up, down, delete = st.columns(6)
            edit.button("编辑", key=f"edit_{index}", on_click=_pipeline_action, args=("edit", index))
            toggle.button("停用" if enabled else "启用", key=f"toggle_{index}", on_click=_pipeline_action, args=("toggle", index))
            copy.button("复制", key=f"copy_{index}", on_click=_pipeline_action, args=("copy", index))
            up.button("↑ 上移", key=f"up_{index}", disabled=index == 0, on_click=_pipeline_action, args=("up", index))
            down.button("↓ 下移", key=f"down_{index}", disabled=index == len(st.session_state.steps) - 1,
                        on_click=_pipeline_action, args=("down", index))
            delete.button("删除", key=f"delete_{index}", on_click=_pipeline_action, args=("delete", index))
    st.button("清空流水线", on_click=_pipeline_action, args=("clear",))


def _render_mapping_details(result: PipelineResult) -> None:
    for stage in result.stages:
        if not stage.mapping_rows:
            continue
        with st.expander(f"第 {stage.index} 步映射明细", expanded=True):
            field_tab, bit_tab = st.tabs(["字段规则", "逐 bit 来源"])
            with field_tab:
                st.dataframe(
                    [
                        {
                            "输出字段": row.output_range,
                            "来源 / 表达式": row.source,
                            "位宽": row.width,
                            "字段值": row.value,
                        }
                        for row in stage.mapping_rows
                    ],
                    width="stretch",
                    hide_index=True,
                )
            with bit_tab:
                st.dataframe(
                    [
                        {
                            "输出 bit": row.output_bit,
                            "来源 / 表达式": row.expression,
                            "结果": row.value,
                        }
                        for row in stage.mapping_bits
                    ],
                    width="stretch",
                    hide_index=True,
                )


def _render_codegen(source: BitVector) -> None:
    with st.expander("生成 SystemVerilog 参考代码"):
        function_name = st.text_input("Function 名称", key="function_name")
        try:
            code = generate_systemverilog(source, st.session_state.steps, function_name)
            if function_name != _safe_identifier(function_name):
                st.caption(f"函数名已规范为：{_safe_identifier(function_name)}")
            st.code(code, language="systemverilog")
            st.download_button(
                "下载 .sv",
                data=code.encode("utf-8"),
                file_name=f"{_safe_identifier(function_name)}.sv",
                mime="text/plain",
            )
        except DataToolError as exc:
            st.error(f"代码生成失败：{exc}")


def _render_pipeline_result(source: BitVector) -> PipelineResult | None:
    try:
        result = run_pipeline(source, st.session_state.steps)
    except DataToolError as exc:
        st.error(f"流水线执行失败：{exc}")
        return None

    st.subheader("转换结果")
    st.code(result.final.to_sv_hex(), language="systemverilog")
    active = sum(step.get("enabled", True) for step in st.session_state.steps)
    st.caption(f"输出 {result.final.width} bit · 已执行 {active} 步 · 可使用代码框右上角按钮复制结果")

    rows: list[dict[str, Any]] = [
        {
            "步骤": 0,
            "操作": "原始输入",
            "位宽": source.width,
            "Hex": source.to_sv_hex(),
            "Binary": _short(source.to_binary()),
        }
    ]
    rows.extend(
        {
            "步骤": stage.index,
            "操作": stage.description,
            "位宽": stage.output_vector.width,
            "Hex": stage.output_vector.to_sv_hex(),
            "Binary": _short(stage.output_vector.to_binary()),
        }
        for stage in result.stages
    )
    st.dataframe(rows, width="stretch", hide_index=True)
    for stage in result.stages:
        for note in stage.notes:
            st.warning(f"第 {stage.index} 步：{note}")
    with st.expander("可交互位映射：点击输出查看来源", expanded=True):
        html = mapping_html(result, st.session_state.steps)
        st.iframe(html, height=760)
        st.download_button("下载交互位映射 HTML", data=html, file_name="chip_bit_mapping.html", mime="text/html")
    _render_mapping_details(result)

    st.subheader("结果格式与 bit 视图")
    _render_bit_grid(result.final, "最终 bit 视图")
    st.table(_vector_rows(result.final))
    st.download_button(
        "下载结果 TXT",
        data=_vector_text(result.final).encode("utf-8-sig"),
        file_name="chip_data_result.txt",
        mime="text/plain",
    )
    _render_codegen(source)
    return result


def _process_batch(text: str, format_hint: str, width: int | None, signed: bool | None) -> None:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        value_text = raw_line.strip()
        if not value_text or value_text.startswith("//"):
            continue
        try:
            parsed = parse_value(value_text, format_hint, width, signed)
            result = run_pipeline(parsed.vector, st.session_state.steps)
            rows.append(
                {
                    "行号": line_number,
                    "原数据": value_text,
                    "结果": result.final.to_sv_hex(),
                    "Unsigned": str(result.final.unsigned_value),
                    "Signed": str(result.final.twos_complement_value),
                    "状态": "OK",
                }
            )
        except DataToolError as exc:
            rows.append(
                {
                    "行号": line_number,
                    "原数据": value_text,
                    "结果": "",
                    "Unsigned": "",
                    "Signed": "",
                    "状态": str(exc),
                }
            )
    st.session_state.batch_results = rows
    st.session_state.batch_fingerprint = _batch_fingerprint(text)
    st.session_state.batch_config = {"format_hint": format_hint, "width": width, "signed": signed,
                                    "steps": deepcopy(st.session_state.steps)}


def _batch_fingerprint(text: str) -> str:
    return fingerprint({"text": text, "format": st.session_state.input_format,
                        "width": st.session_state.input_width, "signed": st.session_state.signed_mode,
                        "steps": st.session_state.steps})


def _batch_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _render_comparison(result: ComparisonResult) -> None:
    if result.matches:
        st.success(f"匹配：所有有效 bit 均相同；忽略 {result.ignored_count} 个 X/Z/? bit。")
    else:
        st.error(
            f"不匹配：{result.different_count} 个 bit 不同；从 MSB 方向遇到的第一个差异是 "
            f"bit[{result.first_difference_msb}]。"
        )
    left, middle, right = st.columns(3)
    left.metric("不同 bit", result.different_count)
    middle.metric("忽略 bit", result.ignored_count)
    right.metric("XOR 差异 Mask", BitVector(result.diff_mask, result.actual.width).to_hex())

    statuses = {item.bit: item.status for item in result.bits}
    expected_values = {item.bit: item.expected for item in result.bits}
    _render_bit_grid(result.actual, "Actual", statuses=statuses)
    _render_bit_grid(result.actual, "Expected", statuses=statuses, expected=expected_values)
    st.dataframe(
        [
            {
                "bit": item.bit,
                "Actual": item.actual,
                "Expected": item.expected,
                "状态": item.status,
            }
            for item in result.bits
        ],
        width="stretch",
        hide_index=True,
    )


st.set_page_config(page_title="芯片数据转换工具", page_icon="🔀", layout="wide")
_init_state()
_install_styles()
_render_template_sidebar()

st.title("芯片数据转换工具")
st.caption("逐 bit 映射 · XOR/逻辑运算 · 数据对比 · Parity/CRC · SystemVerilog 生成")
st.caption("从左到右：输入数据 → 添加转换步骤 → 查看结果与位来源；侧栏可保存或恢复整个工作现场。")

convert_tab, batch_tab, compare_tab, checksum_tab, help_tab = st.tabs(
    ["数据转换", "批量处理", "Actual / Expected 对比", "Parity / CRC", "使用说明"]
)

source_vector: BitVector | None = None
pipeline_result: PipelineResult | None = None

with convert_tab:
    st.subheader("原始数据")
    st.text_area(
        "输入一个数据",
        key="raw_value",
        height=90,
        help="支持 32'h1234_5678、0x12345678、0b1010、十进制和字节流。",
    )
    format_column, width_column, signed_column = st.columns(3)
    format_column.selectbox("输入格式", list(FORMAT_OPTIONS), key="input_format")
    width_column.number_input(
        "数据位宽（0 为自动）",
        min_value=0,
        max_value=4096,
        step=1,
        key="input_width",
    )
    signed_column.selectbox("数据类型", list(SIGNED_OPTIONS), key="signed_mode")

    try:
        parsed_value = parse_value(
            st.session_state.raw_value,
            FORMAT_OPTIONS[st.session_state.input_format],
            int(st.session_state.input_width) or None,
            SIGNED_OPTIONS[st.session_state.signed_mode],
        )
        source_vector = parsed_value.vector
        st.success(
            f"解析成功：{parsed_value.detected_format}，{source_vector.width} bit，"
            f"{'有符号' if source_vector.signed else '无符号'}"
        )
        _render_input_bit_editor(source_vector)
        with st.expander("查看全部输入格式"):
            st.code(_vector_text(source_vector), language="text")
    except DataToolError as exc:
        st.error(f"输入解析失败：{exc}")

    st.divider()
    _render_pipeline_editor()
    if source_vector is not None:
        pipeline_result = _render_pipeline_result(source_vector)

with batch_tab:
    st.write("一行输入一个数据，批量使用当前输入配置和转换流水线。")
    uploaded_batch = st.file_uploader("导入 TXT / CSV", type=["txt", "csv"], key="batch_import")
    if uploaded_batch is not None:
        try:
            if uploaded_batch.size > 10 * 1024 * 1024:
                raise DataToolError("批量文件最多为 10 MB")
            imported_text = uploaded_batch.getvalue().decode("utf-8-sig")
            if uploaded_batch.name.lower().endswith(".csv"):
                reader = csv.DictReader(io.StringIO(imported_text))
                headers = reader.fieldnames or []
                if not headers:
                    raise DataToolError("CSV 必须包含列名；无列名的数据请以 TXT 导入")
                selected_column = st.selectbox("选择数据列", headers)
                imported_text = "\n".join(row.get(selected_column) or "" for row in reader)
            if st.button("将文件数据填入批量输入"):
                st.session_state.batch_text = imported_text
                st.rerun()
        except (UnicodeError, ValueError, csv.Error) as exc:
            st.error(f"文件导入失败：{exc}")
    batch_text = st.text_area("批量数据", height=180, key="batch_text")
    if st.button("执行批量转换", type="primary"):
        _process_batch(batch_text, FORMAT_OPTIONS[st.session_state.input_format],
                       int(st.session_state.input_width) or None, SIGNED_OPTIONS[st.session_state.signed_mode])
    if st.session_state.batch_results:
        stale = st.session_state.get("batch_fingerprint") != _batch_fingerprint(batch_text)
        if stale:
            st.warning("结果已过期：输入或转换配置已修改，请重新执行。旧结果仅供查看，已禁用导出。")
        all_rows = st.session_state.batch_results
        failed = sum(row["状态"] != "OK" for row in all_rows)
        st.caption(f"共 {len(all_rows)} 条 · 成功 {len(all_rows) - failed} · 失败 {failed}")
        failures_only = st.checkbox("只看失败行")
        rows = [row for row in all_rows if row["状态"] != "OK"] if failures_only else all_rows
        st.dataframe(rows, width="stretch", hide_index=True)
        st.download_button("下载 CSV", data=_batch_csv(rows) if rows else b"", file_name="chip_data_batch_result.csv",
                           mime="text/csv", disabled=stale or not rows)
        report = {"kind": "chip-data-batch-report", "version": 1,
                  "configuration": st.session_state.get("batch_config"), "results": all_rows,
                  "fingerprint": st.session_state.get("batch_fingerprint")}
        st.download_button("下载结果与配置 JSON", data=json.dumps(report, ensure_ascii=False, indent=2),
                           file_name="chip_data_batch_report.json", mime="application/json", disabled=stale)

with compare_tab:
    st.subheader("Actual / Expected 逐 bit 对比")
    available_result = pipeline_result.final if pipeline_result is not None else None
    source_mode = st.radio(
        "Actual 来源",
        ["使用当前转换结果", "使用原始输入", "手动输入 Actual"],
        horizontal=True,
        key="actual_source_mode",
    )
    actual_vector: BitVector | None = available_result
    if source_mode == "使用原始输入":
        actual_vector = source_vector
    if source_mode == "手动输入 Actual":
        actual_text = st.text_input("Actual", key="compare_actual")
        try:
            actual_vector = parse_value(actual_text).vector
        except DataToolError as exc:
            st.error(f"Actual 解析失败：{exc}")
            actual_vector = None

    if actual_vector is None:
        st.warning("当前来源没有可用数据。请先修正输入/流水线，或明确选择其他来源。")
    if actual_vector is not None:
        expected_text = st.text_input(
            "Expected（X/Z/? 表示 don't-care）",
            key="compare_expected",
        )
        st.caption("示例：`32'h12XX_??78`。X、Z 和 ? 只在对比页面作为忽略位，不参与算术运算。")
        try:
            comparison = compare_actual_expected(actual_vector, expected_text)
            _render_comparison(comparison)
        except DataToolError as exc:
            st.error(f"Expected 解析失败：{exc}")

with checksum_tab:
    st.subheader("Parity / CRC 计算")
    checksum_mode = st.radio("数据来源", ["使用当前转换结果", "使用原始输入", "手动输入"],
                             horizontal=True, key="checksum_source_mode")
    checksum_source = pipeline_result.final if pipeline_result is not None else None
    if checksum_mode == "使用原始输入":
        checksum_source = source_vector
    elif checksum_mode == "手动输入":
        checksum_text = st.text_input("待校验数据", key="checksum_text")
        try:
            checksum_source = parse_value(checksum_text).vector
        except DataToolError as exc:
            st.error(f"待校验数据解析失败：{exc}")
            checksum_source = None
    if checksum_source is None:
        st.warning("当前来源没有可用数据。请先修正输入/流水线，或明确选择其他来源。")
    else:
        st.caption(f"正在校验：{checksum_mode} · {checksum_source.to_sv_hex()}")
        _render_bit_grid(checksum_source, "校验输入")
        left, right = st.columns(2)
        left.metric("偶校验追加 bit", calculate_parity(checksum_source, "even"))
        right.metric("奇校验追加 bit", calculate_parity(checksum_source, "odd"))
        preset_name = st.selectbox("CRC 预设", list(CRC_PRESETS) + ["自定义"], key="crc_preset")
        order_label = st.radio("CRC 字节输入顺序", ["高字节在前", "低字节在前"], horizontal=True, key="crc_order")
        byte_order = "big" if order_label == "高字节在前" else "little"
        if checksum_source.width % 8 == 0:
            data = checksum_source.value.to_bytes(checksum_source.width // 8, byte_order)
            st.code(" ".join(f"{byte:02X}" for byte in data), language="text")
            st.caption("上方即实际参与 CRC 的字节序列；字节顺序与 refin/refout 的位反射是不同设置。")
        with st.expander("自定义 CRC 参数", expanded=preset_name == "自定义"):
            st.number_input("CRC 位宽（8～64）", min_value=8, max_value=64, key="custom_crc_width")
            st.text_input("Poly（十六进制，不包含最高阶项）", key="custom_crc_poly")
            st.text_input("Init（十六进制）", key="custom_crc_init")
            st.text_input("XorOut（十六进制）", key="custom_crc_xor")
            st.checkbox("RefIn：输入位反射", key="custom_crc_refin")
            st.checkbox("RefOut：输出位反射", key="custom_crc_refout")
        try:
            if preset_name == "自定义":
                try:
                    poly, init, xorout = [int(st.session_state[key].replace("_", "").strip(), 16)
                                          for key in ["custom_crc_poly", "custom_crc_init", "custom_crc_xor"]]
                except ValueError as exc:
                    raise DataToolError("CRC 参数必须是合法十六进制数") from exc
                preset = CRCPreset("自定义", int(st.session_state.custom_crc_width), poly, init,
                                   st.session_state.custom_crc_refin, st.session_state.custom_crc_refout, xorout)
            else:
                preset = CRC_PRESETS[preset_name]
            st.caption(f"poly=0x{preset.polynomial:X} · init=0x{preset.initial:X} · "
                       f"refin={preset.reflect_input} · refout={preset.reflect_output} · xorout=0x{preset.xor_output:X}")
            crc = calculate_crc(checksum_source, preset, byte_order)
            st.success(f"{preset_name} = {crc.to_sv_hex()}")
        except DataToolError as exc:
            st.warning(str(exc))

with help_tab:
    st.markdown(
        """
### 快速开始

1. 在“数据转换”输入数据，选择格式、位宽和数据类型。
2. 添加步骤；每步可编辑、复制、停用、排序。侧栏提供撤销和重做。
3. 展开可交互位映射，选择步骤并点击输出 bit，查看本步来源及原始输入依赖。
4. 输入、输出与对比位视图均支持分页；宽输入也可以逐 bit 点击修改。
5. “批量处理”支持粘贴或导入 UTF-8 TXT / 带列名 CSV。配置改变后必须重新执行才能导出。

### 保存与恢复

侧栏默认自动保存到本项目的 `.local/workspace.json`，新会话恢复最近保存的工作。
同一项目的多个浏览器会话共用这一恢复文件，以最后保存的会话为准。
需要保留多个任务时，请分别导出“工作现场 JSON”；JSON 包含数据和设置，请按项目资料保管。
模板保存的是可复用规则；同名覆盖需明确勾选。最近 40 次撤销仅在当前浏览器会话内有效。

### 来源与计算失败

对比和 CRC 可明确选择转换结果、原始输入或手动输入。
当前流水线出错时，转换结果不可用，程序不会自动退回原始输入。
加减法会提示进位、借位及补码溢出；位宽转换须明确选择补零、符号扩展或保留低位截断。
位映射展示结构依赖，多输入逻辑、归约和加减运算不等同于单根导线的直接拷贝。

### CRC

字节输入顺序和 RefIn/RefOut 位反射分别设置，页面展示实际参与 CRC 的字节序列。
自定义 CRC 支持 8～64 bit；Poly 填十六进制，省略最高阶项。例如 CRC-16/CCITT-FALSE 的 Poly 为 1021。

### 逐 bit 映射

```systemverilog
output[3] = input[0]
output[2] = ~input[1]
output[1] = input[7] ^ input[6]
output[0] = ^input[3:0]
```

- `~`：按位取反。
- `^`、`&`、`|`：两个等宽字段的逐 bit 运算，运算符两侧需要空格。
- `^input[7:0]`：归约异或，结果为 1 bit；也支持归约 `&`、`|` 和 `~^`。
- 每个输出 bit 必须且只能赋值一次，程序会检查越界、重叠和漏赋值。

### 流水线运算

支持 AND、OR、XOR、XNOR、NOT、ADD、SUB、分组归约、逻辑移位、算术右移、循环移位，以及设置、清除或翻转指定 bit。加减和左移按当前位宽截断。

“整段数据”运算会让当前数据与第二运算数逐 bit 运算；“两个指定 bit”运算只读取两个 bit，并把 1-bit 结果写入指定目标 bit，其余位保持不变。

“按 N bit 分组归约”会把每组数据通过 AND、OR、XOR 或 XNOR 压缩成 1 bit。例如从 LSB 开始每 2 bit XOR：`output[0] = ^input[1:0]`、`output[1] = ^input[3:2]`。

### 四态数据

算术和逻辑流水线仍使用确定的二态数据。`X/Z/?` 可在 Actual/Expected 对比页中作为 don't-care，避免把未知态静默转换成 0。

### SystemVerilog

转换成功后展开“生成 SystemVerilog 参考代码”，可以复制或下载与当前流水线对应的 function。生成代码建议在进入正式 testbench 前结合项目的 lint 和仿真规则复核。
"""
    )


ui_state.finish()
