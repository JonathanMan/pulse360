"""
tests/conftest.py
==================
Shared fixtures and mocks for Pulse360's test suite.

Streamlit and Supabase are mocked globally so tests can import
app modules without needing live credentials or a running server.
"""

import sys
import types
import pytest


# ── Stub out Streamlit before any app module is imported ──────────────────────
# This lets us test pure-logic functions that live inside files which also
# contain st.* calls at module level.

class _FakeSessionState(dict):
    """dict-like session_state that supports attribute-style access."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
    def __setattr__(self, key, value):
        self[key] = value
    def get(self, key, default=None):
        return super().get(key, default)
    def pop(self, key, *args):
        return super().pop(key, *args)


def _make_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = _FakeSessionState()
    st.secrets       = {}
    # No-op stubs for every st.* call used in app modules
    for name in (
        "cache_data", "cache_resource", "markdown", "write", "error",
        "warning", "info", "success", "stop", "rerun", "columns",
        "sidebar", "expander", "form", "form_submit_button", "button",
        "text_input", "number_input", "selectbox", "radio", "tabs",
        "tab", "metric", "caption", "header", "subheader", "title",
        "link_button", "set_page_config", "spinner", "empty",
        "data_editor", "dataframe", "switch_page",
    ):
        setattr(st, name, lambda *a, **kw: None)

    # cache_data / cache_resource must return a decorator
    def _passthrough_decorator(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn
    st.cache_data     = _passthrough_decorator
    st.cache_resource = _passthrough_decorator

    # columns() must return iterable of context managers
    class _CM:
        def __enter__(self): return self
        def __exit__(self, *_): pass
    st.columns = lambda *a, **kw: [_CM(), _CM(), _CM()]
    st.sidebar = _CM()

    # st.Page stub — used by get_nav_pages(); tests inspect .title
    class _Page:
        def __init__(self, path, title="", icon="", default=False, **kw):
            self.path    = path
            self.title   = title
            self.icon    = icon
            self.default = default
    st.Page = _Page

    return st


sys.modules.setdefault("streamlit", _make_streamlit_stub())

# Stub supabase so imports don't fail without credentials
_supabase = types.ModuleType("supabase")
_supabase.Client = object
_supabase.create_client = lambda *a, **kw: None
sys.modules.setdefault("supabase", _supabase)

# Stub streamlit_javascript
_stjs = types.ModuleType("streamlit_javascript")
_stjs.st_javascript = lambda *a, **kw: 0
sys.modules.setdefault("streamlit_javascript", _stjs)

# Stub fredapi
_fredapi = types.ModuleType("fredapi")
_fredapi.Fred = object
sys.modules.setdefault("fredapi", _fredapi)

# Stub anthropic
_anthropic = types.ModuleType("anthropic")
_anthropic.Anthropic = object
sys.modules.setdefault("anthropic", _anthropic)

# Stub yfinance
_yf = types.ModuleType("yfinance")
_yf.Ticker = object
sys.modules.setdefault("yfinance", _yf)


@pytest.fixture(autouse=True)
def reset_session_state():
    """Clear fake session state between every test."""
    import streamlit as st
    st.session_state.clear()
    yield
    st.session_state.clear()
