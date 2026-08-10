"""Unit tests for the DocsRagService — retriever, embedder, LLM are all stubbed."""

from __future__ import annotations

from ask_docs_service.application.rag_flow import DocsRagService, _build_prompt, _snippet
from ask_docs_service.domain.models import (
    Citation,
    DocsHit,
    DocsQuery,
    DocsResponse,
)


class _StubEmbedder:
    def __init__(self, vector=None, raises=None):
        self._vector = vector or [0.1, 0.2, 0.3]
        self._raises = raises
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        if self._raises:
            raise self._raises
        return self._vector


class _StubRetriever:
    def __init__(self, hits=None, raises=None):
        self._hits = hits or []
        self._raises = raises
        self.calls: list[dict] = []

    def search_data_products(self, *, text, vector, top_k):
        self.calls.append({"text": text, "vector": vector, "top_k": top_k})
        if self._raises:
            raise self._raises
        return self._hits


class _StubLLM:
    def __init__(self, response_text="The sales_order data product …", raises=None):
        self._text = response_text
        self._raises = raises
        self.calls: list[str] = []

    def invoke(self, prompt: str):
        self.calls.append(prompt)
        if self._raises:
            raise self._raises

        class _R:
            def __init__(self, text):
                self.content = text

        return _R(self._text)


def _hit(
    source_file="inventory.pdf",
    data_product_name="Inventory Situation",
    chunk_text="On-hand stock per plant.",
    score=1.0,
):
    return DocsHit(
        source_file=source_file,
        data_product_name=data_product_name,
        chunk_text=chunk_text,
        score=score,
    )


def test_empty_question_short_circuits():
    svc = DocsRagService(_StubRetriever(), _StubEmbedder(), _StubLLM())
    response = svc.answer(DocsQuery(question=""))
    assert response.error == "Empty docs question."
    assert response.answer == ""
    assert response.citations == []


def test_whitespace_question_short_circuits():
    svc = DocsRagService(_StubRetriever(), _StubEmbedder(), _StubLLM())
    response = svc.answer(DocsQuery(question="   "))
    assert response.error == "Empty docs question."


def test_no_hits_returns_helpful_message():
    svc = DocsRagService(_StubRetriever(hits=[]), _StubEmbedder(), _StubLLM())
    response = svc.answer(DocsQuery(question="What is foo?"))
    assert "No documentation" in response.answer
    assert response.citations == []
    assert response.error is None


def test_happy_path_builds_response_with_citations():
    hits = [
        _hit("inventory.pdf", "Inventory Situation", "On-hand stock per plant.", score=2.5),
        _hit(
            "sales.docx", "Sales Performance", "Open order tracker shows pending orders.", score=2.0
        ),
    ]
    retr = _StubRetriever(hits=hits)
    emb = _StubEmbedder(vector=[0.1, 0.2])
    llm = _StubLLM(response_text="The inventory situation tracks on-hand stock …")
    svc = DocsRagService(retr, emb, llm)

    response = svc.answer(DocsQuery(question="What is the open order tracker?", top_k=5))

    assert isinstance(response, DocsResponse)
    assert response.answer == "The inventory situation tracks on-hand stock …"
    assert response.error is None
    # Both hits become citations, in the same order.
    assert [c.entity_id for c in response.citations] == ["inventory.pdf", "sales.docx"]
    assert all(isinstance(c, Citation) for c in response.citations)
    # Retriever was called with the stripped text + the embedder vector + top_k=5.
    assert retr.calls == [
        {
            "text": "What is the open order tracker?",
            "vector": [0.1, 0.2],
            "top_k": 5,
        }
    ]
    # Embedder saw the stripped question.
    assert emb.calls == ["What is the open order tracker?"]
    # The prompt the LLM saw includes both source files and the question.
    assert "What is the open order tracker?" in llm.calls[0]
    assert "inventory.pdf" in llm.calls[0]
    assert "sales.docx" in llm.calls[0]


def test_embed_failure_returns_pipeline_error():
    svc = DocsRagService(
        _StubRetriever(),
        _StubEmbedder(raises=RuntimeError("AI Core down")),
        _StubLLM(),
    )
    response = svc.answer(DocsQuery(question="x"))
    assert response.error == "AI Core down"
    assert "Pipeline error" in response.answer


def test_retriever_failure_returns_pipeline_error():
    svc = DocsRagService(
        _StubRetriever(raises=RuntimeError("OpenSearch down")),
        _StubEmbedder(),
        _StubLLM(),
    )
    response = svc.answer(DocsQuery(question="x"))
    assert response.error == "OpenSearch down"


def test_llm_failure_keeps_citations():
    """If retrieval succeeded but the LLM blew up, surface the error AND the
    citations — the caller can still show the matched source files."""
    hits = [_hit(source_file="inventory.pdf")]
    svc = DocsRagService(
        _StubRetriever(hits=hits),
        _StubEmbedder(),
        _StubLLM(raises=RuntimeError("LLM rate-limited")),
    )
    response = svc.answer(DocsQuery(question="x"))
    assert response.error == "LLM rate-limited"
    assert "Pipeline error" in response.answer
    assert [c.entity_id for c in response.citations] == ["inventory.pdf"]


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────
def test_build_prompt_includes_each_hit():
    hits = [
        _hit(source_file="a.pdf", chunk_text="content A"),
        _hit(source_file="b.docx", chunk_text="content B"),
    ]
    prompt = _build_prompt("question", hits)
    assert "a.pdf" in prompt
    assert "b.docx" in prompt
    assert "content A" in prompt
    assert "content B" in prompt
    assert "USER QUESTION:\nquestion" in prompt


def test_snippet_truncates_and_collapses_whitespace():
    raw = "line1\n\nline2\n  multi   spaces"
    out = _snippet(raw)
    assert "\n" not in out
    assert "  " not in out
    assert out.startswith("line1 line2 multi spaces")


def test_snippet_respects_max_chars():
    raw = "x" * 1000
    assert len(_snippet(raw)) == 240
