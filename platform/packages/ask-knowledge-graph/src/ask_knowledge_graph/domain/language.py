"""The semantic layer's authoring language — vocabulary + prompt directives.

Pure domain (no I/O). The deployment-level resolution lives in
``infrastructure.language_config``, exactly as ``domain.naming`` /
``infrastructure.naming_config`` split the column-naming flag.

WHY THIS EXISTS (PLAN_SEMANTIC_LANGUAGE.md): retrieval matches a user's question
against the layer's own words, so the language the layer is AUTHORED in and the
language the retrieval query is EXPRESSED in must agree. They did not: the IR
generator hard-mandated English terms while the DDL annotator mirrored the source
language, so a Spanish-authored corpus was searched with an English query — the
BM25 leg matches nothing and the vector leg degrades to cross-lingual similarity.
The failure is silent: a fluent answer over the wrong entity.

WHAT THE FLAG GOVERNS — free text only:

* governed: entity/field ``description``, ``synonyms``, entity ``alias``, and the
  language the IR generator extracts business terms in.
* NOT governed: physical identifiers (``fields[].name``, ids, ``db_table_name``)
  — always folded ASCII, see ``domain.naming``; the closed English vocabularies
  (``business_process`` values, ``field_role``, ``layer``, ``entity_role``);
  Bronze ``alias`` (English by BRONZE_LAYER.md §2, and Bronze never enters
  text-to-SQL retrieval); and the ANSWER language, which mirrors the user's
  question independently (``result_formatter``).

SQL generation never reads this flag.
"""

from __future__ import annotations

from enum import Enum


class SemanticLanguage(str, Enum):
    """Languages the semantic layer can be authored in.

    Deliberately a CLOSED set: each member needs a matching OpenSearch analyzer
    (see PLAN_SEMANTIC_LANGUAGE.md W3) and a prompt label we have actually
    exercised. Adding one is a decision, not a config typo.
    """

    EN = "en"
    ES = "es"

    @property
    def label(self) -> str:
        """The language's English name, for prompt injection ("Spanish")."""
        return _LABELS[self]


_LABELS: dict[SemanticLanguage, str] = {
    SemanticLanguage.EN: "English",
    SemanticLanguage.ES: "Spanish",
}


def authoring_directive(language: SemanticLanguage) -> str:
    """The block appended to AUTHORING prompts (enrichment, DDL annotation).

    Brace-free by contract: some consumers feed it through a
    ``ChatPromptTemplate``, where ``{`` would be read as a template variable.
    """
    lang = language.label
    return (
        f"LANGUAGE OF THE SEMANTIC LAYER — {lang.upper()}\n"
        f"Write every FREE-TEXT value you author in {lang}: entity and field "
        f"`description`, entity `alias`, and `synonyms`. This is the language the "
        f"semantic layer is authored in, so user questions are matched against it.\n"
        f"Do NOT translate, and do NOT write in {lang}:\n"
        f"  - physical column names, table names or entity ids (they are SQL "
        f"identifiers, never prose);\n"
        f"  - the closed vocabularies: `business_process` values (ORDER TO CASH, "
        f"PROCURE TO PAY, PLANT TO PRODUCE, RECORD TO REPORT, ORGANIZATIONAL "
        f"STRUCTURE), `field_role`, `entity_role`, `classification`, `layer` — "
        f"these are enums, keep them exactly as specified;\n"
        f"  - Bronze `alias`, which stays an UPPER_SNAKE English label.\n"
        f"Accents and diacritics are correct and expected in descriptions. Write "
        f"`synonyms` WITHOUT accents so a user typing without them still matches."
    )


def extraction_directive(language: SemanticLanguage) -> str:
    """The block injected into the IR generator's prompt.

    The extracted terms are the RETRIEVAL query: they must be worded like the
    layer, not like the user. Brace-free (same ``ChatPromptTemplate`` reason).
    """
    lang = language.label
    return (
        f"ALL extracted terms MUST be in {lang.upper()}, regardless of the "
        f"language the user writes in. The semantic layer this pipeline searches "
        f"is authored in {lang}, and the extracted terms ARE the retrieval query — "
        f"terms in any other language match neither the keyword index nor the "
        f"embeddings. Translate the user's wording into {lang} business "
        f"vocabulary; keep physical column or table names the user quotes verbatim."
    )
