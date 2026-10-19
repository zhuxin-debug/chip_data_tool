import importlib
import json

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIP_DATA_STATE_DIR", str(tmp_path))
    import ui_state
    importlib.reload(ui_state)
    at = AppTest.from_file("app.py", default_timeout=20).run()
    assert not at.exception
    return at


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_failed_pipeline_never_claims_match_or_crc(app):
    app.session_state.steps = [{"type": "extract", "msb": 100, "lsb": 0}]
    app.run()
    assert not app.exception
    assert any("流水线执行失败" in e.value for e in app.error)
    assert not any("匹配：" in e.value or "CRC-8 =" in e.value for e in app.success)
    app.radio(key="actual_source_mode").set_value("使用原始输入").run()
    assert any("匹配：" in e.value for e in app.success)
    assert not any("CRC-8 =" in e.value for e in app.success)
    app.radio(key="checksum_source_mode").set_value("手动输入").run()
    assert any("8'hF4" in e.value for e in app.success)
    assert not app.exception


@pytest.mark.parametrize("field,value", [("steps", [{"type": "not"}]),
    ("input_width", 64), ("signed_mode", "有符号"),
    ("input_format", "SystemVerilog / 十六进制"), ("batch_text", "8'hA5")])
def test_batch_result_becomes_stale_after_configuration_change(app, field, value):
    button(app, "执行批量转换").click().run()
    assert not app.exception
    previous = app.session_state.batch_results
    app.session_state[field] = value
    app.run()
    assert any("结果已过期" in e.value for e in app.warning)
    downloads = [e for e in app.get("download_button") if e.proto.label == "下载 CSV"]
    assert downloads[0].proto.disabled
    assert app.session_state.batch_results == previous


def test_pipeline_edit_duplicate_disable_and_undo(app):
    app.selectbox(key="new_type").select("提取字段 [MSB:LSB]").run()
    app.number_input(key="new_extract_msb").set_value(7)
    app.number_input(key="new_extract_lsb").set_value(0)
    button(app, "添加到流水线").click().run()
    assert app.session_state.steps[0]["msb"] == 7
    button(app, "编辑").click().run()
    key = next(w.key for w in app.number_input if "edit_" in str(w.key) and str(w.key).endswith("_msb"))
    app.number_input(key=key).set_value(3)
    button(app, "保存修改").click().run()
    assert app.session_state.steps[0]["msb"] == 3
    button(app, "复制").click().run()
    assert len(app.session_state.steps) == 2
    button(app, "停用").click().run()
    assert app.session_state.steps[0]["enabled"] is False
    button(app, "撤销").click().run()
    assert app.session_state.steps[0].get("enabled", True)
    button(app, "重做").click().run()
    assert app.session_state.steps[0]["enabled"] is False
    assert not app.exception


def test_wide_bits_are_editable_by_page(app):
    app.text_area(key="raw_value").set_value("512'h1").run()
    app.selectbox(key="input_bit_page").select(7).run()
    button(app, "511: 0").click().run()
    assert app.session_state.raw_value.startswith("512'h8000")
    assert not app.exception


def test_session_auto_restores_input_pipeline_and_expected(app, tmp_path):
    app.text_area(key="raw_value").set_value("8'hA5").run()
    app.session_state.steps = [{"type": "not"}]
    app.run()
    app.text_input(key="compare_expected").set_value("8'h5A").run()
    document = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert document["state"]["compare_expected"] == "8'h5A"
    fresh = AppTest.from_file("app.py", default_timeout=20).run()
    assert fresh.session_state.raw_value == "8'hA5"
    assert fresh.session_state.steps == [{"type": "not"}]
    assert fresh.session_state.compare_expected == "8'h5A"
    assert any("匹配：" in s.value for s in fresh.success)
    assert not fresh.exception


def test_large_batch_decimals_do_not_overflow_dataframe(app):
    app.text_area(key="batch_text").set_value("128'hFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF").run()
    button(app, "执行批量转换").click().run()
    assert app.session_state.batch_results[0]["Unsigned"] == str((1 << 128) - 1)
    assert not app.exception


def test_undo_is_enabled_immediately_after_the_first_input_change(app):
    original = app.session_state.raw_value
    app.text_area(key="raw_value").set_value("8'hA5").run()
    assert not button(app, "撤销").disabled
    button(app, "撤销").click().run()
    assert app.session_state.raw_value == original
    assert not app.exception
