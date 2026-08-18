# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ResolveIntentUseCase — dispatches a ResolutionRequest to the right strategy.

Concrete implementation of the IntentResolver Protocol. Strategies are kept
as singleton instances so their lazy bundles (graphs, embedder, vector store)
are built once per process.
"""

from __future__ import annotations

import logging

from ..domain.errors import StrategyNotImplementedError
from ..domain.ports import ResolutionRequest
from ..domain.result import IntentResolutionResult, Mode
from ..flash.strategy import FlashStrategy
from ..precise.strategy import PreciseStrategy
from ..smart.strategy import SmartStrategy

logger = logging.getLogger(__name__)


class ResolveIntentUseCase:
    """Single entry point for the orchestrator's SQL_EXECUTION branch."""

    def __init__(
        self,
        flash: FlashStrategy | None = None,
        precise: PreciseStrategy | None = None,
        smart: SmartStrategy | None = None,
    ):
        # Strategies are stateless wrappers over module-level singletons; the
        # constructor accepts overrides only to make the use case testable.
        self._strategies: dict[Mode, FlashStrategy | PreciseStrategy | SmartStrategy] = {
            "flash": flash or FlashStrategy(),
            "precise": precise or PreciseStrategy(),
            "smart": smart or SmartStrategy(),
        }

    def resolve(self, request: ResolutionRequest) -> IntentResolutionResult:
        strategy = self._strategies.get(request.mode)
        if strategy is None:
            raise StrategyNotImplementedError(f"No strategy registered for mode {request.mode!r}")

        logger.info(
            "ResolveIntentUseCase dispatching",
            extra={"mode": request.mode, "session_id": request.session_id},
        )
        return strategy.resolve(request)


# Module-level singleton — orchestrator imports this directly.
_default_use_case: ResolveIntentUseCase | None = None


def get_default_use_case() -> ResolveIntentUseCase:
    global _default_use_case
    if _default_use_case is None:
        _default_use_case = ResolveIntentUseCase()
    return _default_use_case


def reset_default_use_case() -> list[str]:
    """Drop every cached singleton across the intent-resolution package
    (the use-case itself plus each strategy bundle).

    Called by ask-orchestrator's ``/v1/internal/reload`` so the next request
    rebuilds the strategy bundles from a fresh ``settings.json``.
    """
    global _default_use_case
    cleared: list[str] = []

    if _default_use_case is not None:
        cleared.append("resolve_intent_use_case")
    _default_use_case = None

    if FlashStrategy.reset():
        cleared.append("flash_strategy_bundle")
    if PreciseStrategy.reset():
        cleared.append("precise_strategy_bundle")
    if SmartStrategy.reset():
        cleared.append("smart_strategy_bundle")

    return cleared
