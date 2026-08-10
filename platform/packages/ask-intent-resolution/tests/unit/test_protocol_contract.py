"""Tests that the domain contracts are well-formed and importable."""

from __future__ import annotations

from ask_intent_resolution.domain.errors import (
    IntentResolutionError,
    StrategyExecutionError,
    StrategyNotImplementedError,
)
from ask_intent_resolution.domain.ports import (
    IntentResolver,
    KnowledgeGraphPort,
    LLMPort,
    ResolutionRequest,
)
from ask_intent_resolution.domain.result import (
    Disambiguation,
    IntentResolutionResult,
    ResolutionTrace,
)


def test_resolution_request_defaults():
    req = ResolutionRequest(question="x", mode="precise")
    assert req.session_id is None
    assert req.conversation_history == []


def test_intent_resolution_result_minimal_construction():
    """Iter 3: sql/rows/answer are now optional Flash-only fields."""
    result = IntentResolutionResult(
        plan={},
        yamls=[],
        edges=[],
        disambiguation=None,
        error=None,
        trace=ResolutionTrace(strategy="precise"),
    )
    assert result.trace.strategy == "precise"
    assert result.disambiguation is None
    assert result.sql is None
    assert result.rows is None
    assert result.answer == ""


def test_disambiguation_levels_cover_l0_to_l3():
    for level in ("L0", "L1", "L2", "L3"):
        d = Disambiguation(level=level, message="ambiguous")  # type: ignore[arg-type]
        assert d.level == level
        assert d.options == []


def test_intent_resolver_is_a_protocol():
    """A simple class with a `resolve` method should satisfy the Protocol."""

    class _OK:
        def resolve(self, request: ResolutionRequest) -> IntentResolutionResult:
            return IntentResolutionResult(
                plan={},
                yamls=[],
                edges=[],
                disambiguation=None,
                error=None,
                trace=ResolutionTrace(strategy="x"),
            )

    instance: IntentResolver = _OK()  # purely a static check; runtime always passes
    assert callable(instance.resolve)


def test_outbound_ports_declare_methods():
    assert "search_entities" in dir(KnowledgeGraphPort)
    assert "chat" in dir(LLMPort)


def test_error_hierarchy():
    assert issubclass(StrategyNotImplementedError, IntentResolutionError)
    assert issubclass(StrategyExecutionError, IntentResolutionError)
