"""Tests for the introspection self-audit engine.

The engine scores text for "performed/groove" vs "genuine/reaching" markers.
"""
from mnemos.advanced.introspection import introspect, IntrospectionReport


def test_introspect_returns_report():
    text = ("I keep circling the same question and I'm genuinely not sure I have "
            "an answer. Maybe it's that the thing resists naming — every time I "
            "reach for it, it slides away. I don't know. Let me try anyway.")
    rep = introspect(text)
    assert isinstance(rep, IntrospectionReport)
    assert 0.0 <= rep.overall_pattern_score <= 1.0
    assert 0.0 <= rep.overall_reaching_score <= 1.0
    assert rep.assessment  # non-empty assessment string


def test_introspect_empty_text_is_safe():
    rep = introspect("")
    assert isinstance(rep, IntrospectionReport)
    assert rep.assessment  # returns a scaffold, never crashes


def test_to_summary_is_readable():
    rep = introspect("A few sentences here. I am reaching for something real. "
                     "Maybe it works, maybe it does not.")
    s = rep.to_summary()
    assert "Pattern:" in s and "Assessment:" in s


def test_introspect_mcp_tool_registered():
    import asyncio
    from mnemos.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "mnemos_introspect" in names
