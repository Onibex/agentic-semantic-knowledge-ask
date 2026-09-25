# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""invoke_structured — the never-raises contract and the include_raw shape."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from ask_llm_gateway.application.structured import StructuredResult, invoke_structured


class _Schema(BaseModel):
    name: str
    count: int


class _Msg:
    def __init__(self, tokens: int | None):
        self.usage_metadata = {"total_tokens": tokens} if tokens is not None else None


class _Runnable:
    def __init__(self, out):
        self._out = out

    def invoke(self, messages):
        if isinstance(self._out, Exception):
            raise self._out
        return self._out


class _Llm:
    def __init__(self, out):
        self._out = out

    def with_structured_output(self, schema, include_raw=False):
        assert include_raw is True  # the helper must always keep the raw message
        if isinstance(self._out, Exception) and str(self._out) == "bind":
            raise self._out
        return _Runnable(self._out)


def test_parsed_payload_and_tokens():
    out = {"raw": _Msg(123), "parsed": _Schema(name="x", count=2), "parsing_error": None}
    res = invoke_structured(_Llm(out), schema=_Schema, system="s", user="u")
    assert isinstance(res, StructuredResult)
    assert res.parsed.name == "x"
    assert res.tokens == 123
    assert res.error is None


def test_silent_none_parsed_surfaces_error_not_exception():
    # drop_params=True world: provider ignored the schema, parser yielded None.
    out = {"raw": _Msg(77), "parsed": None, "parsing_error": None}
    res = invoke_structured(_Llm(out), schema=_Schema, system="s", user="u")
    assert res.parsed is None
    assert res.tokens == 77  # tokens still accounted even on failure
    assert "no structured payload" in res.error


def test_parsing_error_is_reported():
    out = {"raw": _Msg(10), "parsed": None, "parsing_error": ValueError("bad json")}
    res = invoke_structured(_Llm(out), schema=_Schema, system="s", user="u")
    assert res.parsed is None
    assert "bad json" in res.error


def test_bind_failure_never_raises():
    res = invoke_structured(_Llm(Exception("bind")), schema=_Schema, system="s", user="u")
    assert res.parsed is None
    assert "bind failed" in res.error


def test_invoke_failure_never_raises():
    res = invoke_structured(_Llm(RuntimeError("boom")), schema=_Schema, system="s", user="u")
    assert res.parsed is None
    assert "invoke failed" in res.error


def test_direct_object_return_tolerated():
    # An implementation that ignored include_raw and returned the object.
    res = invoke_structured(_Llm(_Schema(name="d", count=1)), schema=_Schema, system="s", user="u")
    assert res.parsed.name == "d"
    assert res.tokens == 0


_REFUSAL = (
    "400 - LLM Module: Invalid schema for response_format '_Schema': 'required' is "
    "required to be supplied and to be an array including every key in properties. "
    "Missing 'alias'."
)
_LOGGER = "ask_llm_gateway.application.structured"


class _Refusing:
    """Refuses the schema at invoke time, as SAP AI Core's orchestration does in
    strict mode, and answers when the same schema is bound as a tool."""

    def __init__(self, fallback, refusal: str = _REFUSAL):
        self._fallback = fallback
        self._refusal = refusal
        self.methods: list[str | None] = []

    def with_structured_output(self, schema, include_raw=False, method=None):
        assert include_raw is True
        self.methods.append(method)
        if method == "function_calling":
            return _Runnable(self._fallback)
        return _Runnable(RuntimeError(self._refusal))


def test_refused_schema_is_retried_by_function_calling(caplog):
    out = {"raw": _Msg(42), "parsed": _Schema(name="t", count=3), "parsing_error": None}
    llm = _Refusing(out)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        res = invoke_structured(llm, schema=_Schema, system="s", user="u")
    assert llm.methods == [None, "function_calling"]
    assert res.parsed.name == "t"
    assert res.tokens == 42
    assert res.error is None
    assert "Missing 'alias'" in caplog.text


def test_failed_fallback_reports_the_first_error(caplog):
    llm = _Refusing(RuntimeError("tool call refused too"))
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        res = invoke_structured(llm, schema=_Schema, system="s", user="u")
    assert res.parsed is None
    assert "invoke failed" in res.error
    assert "Missing 'alias'" in res.error
    assert "tool call refused too" in caplog.text


def test_log_keeps_the_reason_and_cuts_the_echoed_prompt(caplog):
    llm = _Refusing(RuntimeError("down"), refusal=_REFUSAL + " intermediate_results: " + "x" * 5000)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        invoke_structured(llm, schema=_Schema, system="s", user="u")
    first = caplog.records[0].getMessage()
    assert "Missing 'alias'" in first
    assert len(first) < 700
