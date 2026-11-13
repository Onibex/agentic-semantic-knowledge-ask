# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
src/pipeline/graph/fase1_ir_graph.py
─────────────────────────────────────────────────────────────────────────────
Sub-graph LangGraph — Phase 1: SemanticPlanIR Generation + Disambiguation.

Responsibility:
  Given a `question`, produce a `plan_ir_dict` with BUSINESS TERMS ready
  for Phase 2 (Entity Resolution). This sub-graph NEVER resolves physical
  columns — it only works at the semantic/business level.

Separation of concerns:
  - generate_ir_node:       LLM extracts business terms from user question.
  - dictionary_check_node:  LAST RESORT when the LLM extracted nothing
                            (metrics=[] AND dimensions=[]). Uses hybrid search
                            to find business terms in the Semantic Dictionary.
  - Phase 2 (downstream):   Resolves business terms → physical columns.
                            Also handles phrase expansion via dictionary short-circuit.

3-Level Disambiguation (only when IR is empty):
  Level 1 — Single module:  populate IR with business terms from dictionary.
  Level 2 — Multi-module:   populate IR with the top module's terms and keep
                            the other modules' terms as `alternative_readings`.
                            The SQL generator weighs them: in the chat it may
                            ask the user once, elsewhere it assumes and says so.
  Level 3 — No match:       `unrelated`: nothing in the message maps to the
                            semantic layer.
The graph writes no text for the user: the orchestrator answers an unrelated
message in the user's language.

Topology:
─────────────────────────────────────────────────────────────────────────────

           START
             │
      [generate_ir_node]          ← LLM extracts business terms
             │
         ir_router
      ┌──────┼──────────────┐
      │ error, unrelated    │ ok
      ▼                     ▼
     END         [dictionary_check_node]  ← only if IR is empty
                            │
                           END
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from ask_intent_resolution.precise.domain.ir_models import SemanticPlanIR
from ask_knowledge_graph.application._legacy_dictionary import (
    SemanticDictionaryService,
)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL SUB-GRAPH STATE
# ─────────────────────────────────────────────────────────────────────────────


class Phase1State(TypedDict, total=False):
    question: str
    original_question: str | None
    user_role_id: str | None
    user_department: str | None
    plan_ir_dict: dict[str, Any] | None
    # Level 2: the other modules' terms, "MODULE: label, label".
    alternative_readings: list[str] | None
    # Level 3, or a message the IR judged not analytical.
    unrelated: bool | None
    error: str | None


# ─────────────────────────────────────────────────────────────────────────────
# SUB-GRAPH FACTORY
# ─────────────────────────────────────────────────────────────────────────────


def build_fase1_graph(
    ir_generator,
    semantic_dictionary: SemanticDictionaryService | None = None,
    embedder=None,
):
    """
    Builds the Phase 1 sub-graph: IR generation + dictionary fallback.

    The graph is compiled without a checkpointer, so every invoke starts from
    its input alone. With one keyed by chat session, LangGraph merges each new
    input into the previous turn's state, and any key the new turn does not
    write (``error``, ``unrelated``, ``plan_ir_dict``) answers for
    it, so one non-analytical message would fail every later question of the chat.

    Args:
        ir_generator:        IRGeneratorService
        semantic_dictionary: SemanticDictionaryService (hybrid search)
        embedder:            the active embedder from build_embedder (query vectors)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # NODE 1: generate_ir_node
    # Extracts business terms from the user's question via LLM.
    # ─────────────────────────────────────────────────────────────────────────
    def generate_ir_node(state: Phase1State) -> Phase1State:
        question = state["question"]
        print(f"\n⚙️  [generate_ir_node] '{question[:70]}'")

        try:
            plan_ir: SemanticPlanIR = ir_generator.generate_plan(question)

            if plan_ir.is_impossible:
                return {"unrelated": True}

            plan_dict = plan_ir.model_dump()
            print("   ✅ Plan IR generated.")
            print(f"   metrics={plan_dict.get('semantic_metrics', [])}")
            print(f"   dimensions={plan_dict.get('semantic_dimensions', [])}")
            return {"plan_ir_dict": plan_dict}

        except Exception as exc:
            return {"error": f"IRGeneratorService error: {exc}"}

    # ─────────────────────────────────────────────────────────────────────────
    # NODE 2: dictionary_check_node
    #
    # ONLY activates when the IR is completely empty (no metrics AND no
    # dimensions). This means the LLM couldn't extract any business terms.
    #
    # When it activates, it searches the Semantic Dictionary with the user's
    # full question and populates the IR with BUSINESS TERMS (canonical_labels),
    # never with physical columns. Phase 2 handles physical resolution.
    # ─────────────────────────────────────────────────────────────────────────
    def dictionary_check_node(state: Phase1State) -> Phase1State:
        plan_dict = state.get("plan_ir_dict")
        if not plan_dict:
            return {}

        metrics = plan_dict.get("semantic_metrics", [])
        dimensions = plan_dict.get("semantic_dimensions", [])

        # ── PASS-THROUGH: IR has content → Phase 2 will handle resolution ──
        if metrics or dimensions:
            return {}

        # ── EMPTY IR: LLM couldn't extract anything → dictionary fallback ──
        question = state.get("question", "")
        module_hint = plan_dict.get("module_hint")

        print("\n🔍 [dictionary_check_node] Empty IR — searching dictionary.")

        if not semantic_dictionary or not embedder:
            return {"unrelated": True}

        try:
            query_vector = embedder.embed_query(question)
        except Exception as e:
            print(f"   ⚠️  Embedding failed: {e}")
            return {"unrelated": True}

        results = semantic_dictionary.search_hybrid(
            query=question,
            query_vector=query_vector,
            module=module_hint,
            size=15,
        )

        if not results:
            print("   ❌ [Level 3] No matches.")
            return {"unrelated": True}

        # ── Group by module ───────────────────────────────────────────────
        by_module: dict[str, list[dict]] = defaultdict(list)
        for r in results:
            by_module[r.get("module", "UNKNOWN")].append(r)

        # ── Determine if one module dominates ─────────────────────────────
        module_scores = {
            mod: max(e.get("_score", 0) for e in entries) for mod, entries in by_module.items()
        }
        ranked = sorted(module_scores.items(), key=lambda x: x[1], reverse=True)
        top_module, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        is_single_module = (
            len(ranked) == 1 or second_score == 0 or top_score / max(second_score, 0.001) > 1.5
        )

        # ── Level 1 (and Level 2): populate IR with the top module's terms ──
        found_metrics = []
        found_dimensions = []

        for entry in by_module[top_module]:
            label = entry.get("canonical_label", "")
            if not label:
                continue
            entry_type = entry.get("type", "")
            if entry_type == "metric":
                found_metrics.append(label)
            elif entry_type in ("dimension", "identifier", "timestamp", "filter"):
                found_dimensions.append(label)
            elif entry_type == "phrase":
                # Phrases go as a single business term — Phase 2 will
                # expand them via dictionary short-circuit
                found_dimensions.append(label)

        # Deduplicate
        found_metrics = list(dict.fromkeys(found_metrics))
        found_dimensions = list(dict.fromkeys(found_dimensions))

        if not found_metrics and not found_dimensions:
            print("   ⚠️  [Level 3] Results found but no labeled entries.")
            return {"unrelated": True}

        enriched = dict(plan_dict)
        enriched["semantic_metrics"] = found_metrics
        enriched["semantic_dimensions"] = found_dimensions
        if not enriched.get("module_hint"):
            enriched["module_hint"] = top_module

        if is_single_module:
            print(
                f"   ✅ [Level 1] → module={top_module}, "
                f"metrics={found_metrics}, dims={found_dimensions}"
            )
            return {"plan_ir_dict": enriched}

        # ── Level 2: the other modules' terms travel as alternative readings ──
        alternatives = []
        for mod, _score in ranked[1:]:
            labels = [
                e.get("canonical_label") or e.get("technical_name", "") for e in by_module[mod][:5]
            ]
            labels = [label for label in labels if label]
            if labels:
                alternatives.append(f"{mod}: {', '.join(labels)}")
        print(f"   ⚠️  [Level 2] → module={top_module}, alternatives={alternatives}")
        return {"plan_ir_dict": enriched, "alternative_readings": alternatives}

    # ─────────────────────────────────────────────────────────────────────────
    # ROUTER
    # ─────────────────────────────────────────────────────────────────────────
    def ir_router(state: Phase1State) -> str:
        if state.get("unrelated") or (state.get("error") and not state.get("plan_ir_dict")):
            return "stop"
        return "dictionary_check_node"

    # ─────────────────────────────────────────────────────────────────────────
    # BUILD GRAPH
    # ─────────────────────────────────────────────────────────────────────────
    sg = StateGraph(Phase1State)

    sg.add_node("generate_ir_node", generate_ir_node)
    sg.add_node("dictionary_check_node", dictionary_check_node)

    sg.add_edge(START, "generate_ir_node")
    sg.add_conditional_edges(
        "generate_ir_node",
        ir_router,
        {"dictionary_check_node": "dictionary_check_node", "stop": END},
    )
    sg.add_edge("dictionary_check_node", END)

    return sg.compile()
