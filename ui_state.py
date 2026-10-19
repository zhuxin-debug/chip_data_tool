"""Streamlit state integration; core documents remain UI-independent."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import streamlit as st

from core.errors import DataToolError
from core.templates import atomic_write
from core.workspace import DEFAULTS, snapshot, validate_workspace, workspace_document

STATE_PATH = Path(os.environ.get("CHIP_DATA_STATE_DIR", Path(__file__).resolve().parent / ".local")) / "workspace.json"


def initialize() -> None:
    if "_initialized" not in st.session_state:
        state = deepcopy(DEFAULTS)
        if STATE_PATH.exists():
            try:
                state = validate_workspace(json.loads(STATE_PATH.read_text(encoding="utf-8-sig")))
                st.session_state._restore_message = "已恢复上次保存在本机的工作现场"
            except (DataToolError, OSError, ValueError) as exc:
                st.session_state._restore_message = f"上次工作现场无法恢复，已使用默认值：{exc}"
        st.session_state.update(state)
        st.session_state._initialized = True
        st.session_state._history = [snapshot(st.session_state)]
        st.session_state._future = []
    # Keep conditional widgets' values when Streamlit removes hidden widgets.
    for key, value in st.session_state.get("_retained", {}).items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(value)
    for key, default in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(default)
    for key, value in {"batch_results": [], "_editing": None, "_editor_revision": 0}.items():
        if key not in st.session_state:
            st.session_state[key] = value


def checkpoint() -> None:
    current = snapshot(st.session_state)
    if current != st.session_state._history[-1]:
        st.session_state._history = (st.session_state._history + [current])[-40:]
        st.session_state._future = []


def restore(state: dict) -> None:
    st.session_state.update(deepcopy(state))
    st.session_state._retained = deepcopy(state)
    st.session_state._editing = None
    st.session_state._editor_revision += 1


def undo() -> None:
    checkpoint()
    if len(st.session_state._history) > 1:
        history = st.session_state._history
        st.session_state._future.append(history[-1])
        st.session_state._history = history[:-1]
        restore(history[-2])


def redo() -> None:
    if st.session_state._future:
        state = st.session_state._future.pop()
        st.session_state._history.append(state)
        restore(state)


def finish() -> None:
    checkpoint()
    st.session_state._retained = snapshot(st.session_state)
    if st.session_state.get("autosave", True):
        document = workspace_document(st.session_state)
        if document != st.session_state.get("_last_saved"):
            try:
                atomic_write(STATE_PATH, document)
                st.session_state._last_saved = document
            except OSError as exc:
                st.warning(f"自动保存失败，仍可导出工作现场：{exc}")
