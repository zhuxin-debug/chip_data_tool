from __future__ import annotations

import csv
import io
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
    defaults: dict[str, Any] = {
        "steps": [],
        "input_format": "自动识别",
        "input_width": 0,
        "signed_mode": "自动",
        "raw_value": "32'h1234_5678",
        "batch_results": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
    shown_width = min(vector.width, 256)
    highest = vector.width - 1
    lowest = vector.width - shown_width
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
    if vector.width > shown_width:
        st.caption(f"位宽较大，页面只展示最高 {shown_width} bit；完整数据仍参与所有计算。")


def _toggle_input_bit(value: int, width: int, signed: bool, bit: int) -> None:
    toggled = BitVector(value ^ (1 << bit), width, signed)
    st.session_state.raw_value = toggled.to_sv_hex()


def _render_input_bit_editor(vector: BitVector) -> None:
    st.markdown(
        f"**输入 bit 视图** · `{vector.width} bit` · bit 顺序 `MSB → LSB` · 点击切换 `0/1`"
    )
    if vector.width > 256:
        _render_bit_grid(vector, "只读预览")
        st.warning("位宽超过 256 bit 时关闭逐 bit 按钮，避免一次创建过多界面控件。")
        return

    group_high = vector.width - 1
    while group_high >= 0:
        group_low = max(0, group_high - 7)
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
                use_container_width=True,
                on_click=_toggle_input_bit,
                args=(vector.value, vector.width, vector.signed, bit),
            )
        group_high = group_low - 1


def _render_template_sidebar() -> None:
    with st.sidebar:
        st.header("转换模板")
        templates = list_templates(CONFIG_DIR)
        if templates:
            selected = st.selectbox("已有模板", templates)
            if st.button("加载模板", use_container_width=True):
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
                    st.success(f"已加载：{selected}")
                    st.rerun()
                except DataToolError as exc:
                    st.error(str(exc))
        else:
            st.caption("还没有模板")

        st.divider()
        template_name = st.text_input("新模板名称", placeholder="例如 PCIe_Header")
        if st.button("保存当前规则", use_container_width=True):
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
                    },
                )
                st.success(f"已保存：{path.stem}")
            except DataToolError as exc:
                st.error(str(exc))

        st.divider()
        st.caption("数据和模板均保存在本机，不会上传。")


def _build_step() -> dict[str, Any]:
    operation_label = st.selectbox("操作类型", list(OPERATION_OPTIONS))
    operation_type = OPERATION_OPTIONS[operation_label]
    step: dict[str, Any] = {"type": operation_type}

    if operation_type in {"reverse_units", "reverse_bits_in_units"}:
        step["unit_bits"] = st.selectbox(
            "操作单位",
            [4, 8, 16, 32, 64],
            index=1,
            format_func=lambda value: f"{value} bit" + ("（Byte）" if value == 8 else ""),
        )
    elif operation_type == "extract":
        left, right = st.columns(2)
        step["msb"] = int(left.number_input("MSB", min_value=0, value=23, step=1))
        step["lsb"] = int(right.number_input("LSB", min_value=0, value=8, step=1))
    elif operation_type == "mapping":
        mode = st.radio("映射示例", ["字段映射", "逐 bit / 表达式映射"], horizontal=True)
        step["specification"] = st.text_area(
            "映射规则",
            value=DEFAULT_MAPPING if mode == "字段映射" else BIT_MAPPING_EXAMPLE,
            height=180,
            help="支持单 bit、取反、逐 bit 运算和归约运算；每个输出 bit 必须赋值一次。",
        )
        step["output_width"] = int(
            st.number_input(
                "输出位宽（0 表示根据最高 output bit 自动推断）",
                min_value=0,
                max_value=4096,
                value=0,
                step=1,
            )
        )
        st.caption("表达式示例：`~input[3]`、`input[7] ^ input[2]`、`^input[7:0]`。二元运算符两侧请留空格。")
    elif operation_type == "binary":
        operator = st.selectbox("运算符", ["XOR", "AND", "OR", "XNOR", "ADD", "SUB"])
        step["operator"] = operator
        step["operand"] = st.text_input(
            "第二运算数",
            value="8'hFF",
            help="可以是定宽常量，也可以是当前数据的字段，例如 input[7:0]。短操作数会补零。",
        )
        if operator in {"ADD", "SUB"}:
            st.caption("加减结果按当前位宽截断，行为与 RTL 定宽赋值一致。")
    elif operation_type == "bit_logic":
        left, operation, right, target = st.columns(4)
        step["left_bit"] = int(
            left.number_input("左 bit", min_value=0, value=7, step=1)
        )
        step["operator"] = operation.selectbox(
            "逻辑运算", ["AND", "OR", "XOR", "XNOR"]
        )
        step["right_bit"] = int(
            right.number_input("右 bit", min_value=0, value=6, step=1)
        )
        step["target_bit"] = int(
            target.number_input("写入目标 bit", min_value=0, value=0, step=1)
        )
        st.caption(
            "只把逻辑结果写入目标 bit，其余 bit 保持不变。例如：bit[0] = bit[7] XOR bit[6]。"
        )
    elif operation_type == "group_reduce":
        operator_column, bits_column, direction_column = st.columns(3)
        step["operator"] = operator_column.selectbox(
            "归约运算", ["XOR", "AND", "OR", "XNOR"]
        )
        step["group_bits"] = int(
            bits_column.number_input(
                "每组位数", min_value=1, max_value=4096, value=2, step=1
            )
        )
        direction_labels = {"从 LSB 开始": "lsb", "从 MSB 开始": "msb"}
        direction_label = direction_column.selectbox("分组输出顺序", list(direction_labels))
        step["direction"] = direction_labels[direction_label]
        st.caption(
            "每组归约成 1 bit，输入位宽必须能被每组位数整除。默认：output[0] 由最低一组 input[N-1:0] 产生。"
        )
    elif operation_type == "shift":
        direction_labels = {
            "逻辑左移": "left",
            "逻辑右移": "right",
            "算术右移": "arithmetic_right",
        }
        label = st.selectbox("移位类型", list(direction_labels))
        step["direction"] = direction_labels[label]
        step["count"] = int(st.number_input("移位数量", min_value=0, value=1, step=1))
    elif operation_type == "rotate":
        direction_labels = {"循环左移": "left", "循环右移": "right"}
        label = st.selectbox("循环移位类型", list(direction_labels))
        step["direction"] = direction_labels[label]
        step["count"] = int(st.number_input("循环移位数量", min_value=0, value=1, step=1))
    elif operation_type == "bit_edit":
        action_labels = {"置为 1": "set", "清为 0": "clear", "翻转": "toggle"}
        step["bit_index"] = int(st.number_input("bit 编号", min_value=0, value=0, step=1))
        action_label = st.selectbox("操作", list(action_labels))
        step["action"] = action_labels[action_label]
    elif operation_type == "append_parity":
        mode_labels = {"偶校验": "even", "奇校验": "odd"}
        position_labels = {"追加到 LSB": "lsb", "追加到 MSB": "msb"}
        left, right = st.columns(2)
        step["mode"] = mode_labels[left.selectbox("Parity 类型", list(mode_labels))]
        step["position"] = position_labels[right.selectbox("追加位置", list(position_labels))]
    return step


def _render_pipeline_editor() -> None:
    st.subheader("转换流水线")
    with st.expander("添加转换步骤", expanded=not st.session_state.steps):
        step = _build_step()
        if st.button("添加到流水线", type="primary"):
            st.session_state.steps.append(step)
            st.rerun()

    if not st.session_state.steps:
        st.info("当前没有转换步骤；解析结果将直接作为最终结果。")
        return

    for index, step in enumerate(list(st.session_state.steps)):
        description, up, down, delete = st.columns([8, 1, 1, 1])
        description.write(f"**{index + 1}. {describe_step(step)}**")
        if up.button("↑", key=f"up_{index}", disabled=index == 0, help="上移"):
            st.session_state.steps[index - 1], st.session_state.steps[index] = (
                st.session_state.steps[index],
                st.session_state.steps[index - 1],
            )
            st.rerun()
        if down.button(
            "↓",
            key=f"down_{index}",
            disabled=index == len(st.session_state.steps) - 1,
            help="下移",
        ):
            st.session_state.steps[index + 1], st.session_state.steps[index] = (
                st.session_state.steps[index],
                st.session_state.steps[index + 1],
            )
            st.rerun()
        if delete.button("×", key=f"delete_{index}", help="删除"):
            st.session_state.steps.pop(index)
            st.rerun()

    if st.button("清空流水线"):
        st.session_state.steps = []
        st.rerun()


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
                    use_container_width=True,
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
                    use_container_width=True,
                    hide_index=True,
                )


def _render_codegen(source: BitVector) -> None:
    with st.expander("生成 SystemVerilog 参考代码"):
        function_name = st.text_input("Function 名称", value="transform_data")
        try:
            code = generate_systemverilog(source, st.session_state.steps, function_name)
            st.code(code, language="systemverilog")
            st.download_button(
                "下载 .sv",
                data=code.encode("utf-8"),
                file_name=f"{function_name or 'transform_data'}.sv",
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
    st.dataframe(rows, use_container_width=True, hide_index=True)
    _render_mapping_details(result)

    st.subheader("最终结果")
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
                    "Unsigned": result.final.unsigned_value,
                    "Signed": result.final.twos_complement_value,
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
        use_container_width=True,
        hide_index=True,
    )


st.set_page_config(page_title="芯片数据转换工具", page_icon="🔀", layout="wide")
_init_state()
_install_styles()
_render_template_sidebar()

st.title("芯片数据转换工具")
st.caption("逐 bit 映射 · XOR/逻辑运算 · 数据对比 · Parity/CRC · SystemVerilog 生成")

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
    batch_text = st.text_area(
        "批量数据",
        value="32'h1234_5678\n32'hAABB_CCDD\n32'h0000_1234",
        height=180,
        key="batch_text",
    )
    if st.button("执行批量转换", type="primary"):
        _process_batch(
            batch_text,
            FORMAT_OPTIONS[st.session_state.input_format],
            int(st.session_state.input_width) or None,
            SIGNED_OPTIONS[st.session_state.signed_mode],
        )
    if st.session_state.batch_results:
        st.dataframe(st.session_state.batch_results, use_container_width=True, hide_index=True)
        st.download_button(
            "下载 CSV",
            data=_batch_csv(st.session_state.batch_results),
            file_name="chip_data_batch_result.csv",
            mime="text/csv",
        )

with compare_tab:
    st.subheader("Actual / Expected 逐 bit 对比")
    available_result = pipeline_result.final if pipeline_result else source_vector
    source_mode = st.radio(
        "Actual 来源",
        ["使用当前转换结果", "手动输入 Actual"],
        horizontal=True,
        disabled=available_result is None,
    )
    actual_vector: BitVector | None = available_result
    if source_mode == "手动输入 Actual" or available_result is None:
        actual_text = st.text_input("Actual", value="32'h1234_5678")
        try:
            actual_vector = parse_value(actual_text).vector
        except DataToolError as exc:
            st.error(f"Actual 解析失败：{exc}")
            actual_vector = None

    if actual_vector is not None:
        expected_text = st.text_input(
            "Expected（X/Z/? 表示 don't-care）",
            value=actual_vector.to_sv_hex(),
            key=f"compare_expected_{actual_vector.width}",
        )
        st.caption("示例：`32'h12XX_??78`。X、Z 和 ? 只在对比页面作为忽略位，不参与算术运算。")
        try:
            comparison = compare_actual_expected(actual_vector, expected_text)
            _render_comparison(comparison)
        except DataToolError as exc:
            st.error(f"Expected 解析失败：{exc}")

with checksum_tab:
    st.subheader("Parity / CRC 计算")
    checksum_source = pipeline_result.final if pipeline_result else source_vector
    checksum_mode = st.radio(
        "数据来源",
        ["使用当前转换结果", "手动输入"],
        horizontal=True,
        disabled=checksum_source is None,
        key="checksum_source_mode",
    )
    if checksum_mode == "手动输入" or checksum_source is None:
        checksum_text = st.text_input("待校验数据", value="72'h3132_3334_3536_3738_39")
        try:
            checksum_source = parse_value(checksum_text).vector
        except DataToolError as exc:
            st.error(f"待校验数据解析失败：{exc}")
            checksum_source = None

    if checksum_source is not None:
        _render_bit_grid(checksum_source, "校验输入")
        parity_even = calculate_parity(checksum_source, "even")
        parity_odd = calculate_parity(checksum_source, "odd")
        parity_left, parity_right = st.columns(2)
        parity_left.metric("偶校验追加 bit", parity_even)
        parity_right.metric("奇校验追加 bit", parity_odd)

        preset_name = st.selectbox("CRC 预设", list(CRC_PRESETS))
        preset = CRC_PRESETS[preset_name]
        st.caption(
            f"poly=0x{preset.polynomial:X} · init=0x{preset.initial:X} · "
            f"refin={preset.reflect_input} · refout={preset.reflect_output} · xorout=0x{preset.xor_output:X}"
        )
        try:
            crc = calculate_crc(checksum_source, preset)
            st.success(f"{preset_name} = {crc.to_sv_hex()}")
        except DataToolError as exc:
            st.warning(str(exc))

with help_tab:
    st.markdown(
        """
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
