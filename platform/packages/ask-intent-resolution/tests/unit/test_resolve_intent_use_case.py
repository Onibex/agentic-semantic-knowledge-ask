# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Dispatch tests for ResolveIntentUseCase using fake strategies."""

from __future__ import annotations

import pytest

from ask_intent_resolution.application.resolve_intent_use_case import (
    ResolveIntentUseCase,
)
from ask_intent_resolution.domain.errors import StrategyNotImplementedError
from ask_intent_resolution.domain.ports import ResolutionRequest
from ask_intent_resolution.domain.result import (
    IntentResolutionResult,
    ResolutionTrace,
)


class _FakeStrategy:
    def __init__(self, label: str):
        self.label = label
        self.calls: list[ResolutionRequest] = []

    def resolve(self, request: ResolutionRequest) -> IntentResolutionResult:
        self.calls.append(request)
        return IntentResolutionResult(
            plan={"label": self.label},
            yamls=[],
            edges=[],
            disambiguation=None,
            error=None,
            trace=ResolutionTrace(strategy=self.label),
            answer=f"answered by {self.label}",
        )


def _build_use_case():
    return ResolveIntentUseCase(
        flash=_FakeStrategy("flash"),  # type: ignore[arg-type]
        precise=_FakeStrategy("precise"),  # type: ignore[arg-type]
        smart=_FakeStrategy("smart"),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("mode", ["flash", "precise", "smart"])
def test_dispatches_to_matching_strategy(mode):
    uc = _build_use_case()
    req = ResolutionRequest(question="how many?", mode=mode)
    result = uc.resolve(req)
    assert result.trace.strategy == mode
    assert result.plan == {"label": mode}
    assert result.answer == f"answered by {mode}"


def test_unknown_mode_raises():
    uc = _build_use_case()
    req = ResolutionRequest(question="x", mode="turbo")  # type: ignore[arg-type]
    with pytest.raises(StrategyNotImplementedError):
        uc.resolve(req)


def test_each_strategy_only_invoked_for_its_mode():
    flash, precise, smart = _FakeStrategy("flash"), _FakeStrategy("precise"), _FakeStrategy("smart")
    uc = ResolveIntentUseCase(flash=flash, precise=precise, smart=smart)  # type: ignore[arg-type]

    uc.resolve(ResolutionRequest(question="a", mode="precise"))
    uc.resolve(ResolutionRequest(question="b", mode="precise"))
    uc.resolve(ResolutionRequest(question="c", mode="smart"))

    assert len(flash.calls) == 0
    assert len(precise.calls) == 2
    assert len(smart.calls) == 1
