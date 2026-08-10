"""BronzeNode's hard key/alias contract.

The official Bronze checklist has always demanded these four rules (non-empty +
duplicate-free ``primary_key``, ``primary_key`` ⊆ ``fields``, two-way
``key_field`` agreement, in-file alias uniqueness) plus a well-formed ``id``.
None of them were implemented: BronzeNode carried only a layer check, so the 9
duplicated-``primary_key`` YAMLs in the corpus validated silently.

Malformed input is now REJECTED, not repaired. Normalization (row dedup, alias
sanitization) happens upstream in ``SapJsonParser`` / ``EntityDeriver``, so real
payloads pass — see ``test_sap_parser_parity``.
"""

import pytest
from pydantic import ValidationError

from ask_knowledge_graph.domain.nodes import BronzeNode


def _bronze(**over):
    """A minimal VALID bronze node — VBAK-shaped, MANDT included on purpose."""
    raw = {
        "id": "bronze_s4h_vbak_order_header",
        "layer": "bronze",
        "version": "1",
        "source_system": "s4h",
        "source_system_id": 100,
        "name": "VBAK",
        "alias": "ORDER_HEADER",
        "description": "Sales Document: Header Data",
        "primary_key": ["VBELN"],
        "fields": {
            "MANDT": {
                "type": "STRING(3)",
                "alias": "client",
                "key_field": False,
                "description": "Client",
            },
            "VBELN": {
                "type": "STRING(10)",
                "alias": "sales_doc",
                "key_field": True,
                "description": "Sales document",
            },
        },
    }
    raw.update(over)
    return raw


def test_valid_bronze_passes_and_keeps_mandt_out_of_the_key():
    """The baseline must validate, including SAP's client column.

    MANDT is physically part of every SAP table key but is declared
    ``key_field: false`` and left out of ``primary_key`` in 45/45 shipped files.
    The agreement rule is defined against the DECLARED key, so this is legal —
    if it were not, every SAP bronze in existence would be rejected.
    """
    node = BronzeNode.model_validate(_bronze())
    assert node.primary_key == ["VBELN"]
    assert node.fields["MANDT"].key_field is False


@pytest.mark.parametrize(
    "bad_id",
    [
        "BRONZE_S4H_VBAK_ORDER_HEADER",  # uppercase
        "bronze_s4h_vbak",  # missing the alias segment
        "silver_s4h_sd_sales_order",  # wrong layer prefix
        "bronze_s4h_tspat_sales_div_txt�",  # the real mojibake defect
        "bronze_s4h_vbak_order_header\n",  # trailing newline ($ would accept this)
    ],
)
def test_malformed_id_is_rejected(bad_id):
    with pytest.raises(ValidationError, match="must follow the pattern"):
        BronzeNode.model_validate(_bronze(id=bad_id))


def test_empty_primary_key_is_accepted_when_no_field_is_flagged():
    """Keyless Bronze is ACCEPTED (owner decision 2026-08-03): `key_field` is
    the data-product author's declaration, consumed as authority — an export
    table declaring no key ingests keyless (warned at the parser) and is
    escalated upstream, not rejected. An empty key with zero flagged fields is
    self-consistent under the two-direction agreement rule; a flagged field
    with an empty declared key still fails (see the agreement tests below)."""
    fields = _bronze()["fields"]
    for fdef in fields.values():
        fdef["key_field"] = False
    node = BronzeNode.model_validate(_bronze(primary_key=[], fields=fields))
    assert node.primary_key == []


def test_duplicated_primary_key_is_rejected():
    """The exact corpus defect: 9 shipped YAMLs repeat the whole key tuple 2-4x
    (bkpf 3x, bseg 4x, knvp 4x, mard 3x…) because the parser appended one member
    per duplicated source row."""
    with pytest.raises(ValidationError, match="repeats columns"):
        BronzeNode.model_validate(_bronze(primary_key=["VBELN", "VBELN"]))


def test_primary_key_member_absent_from_fields_is_rejected():
    with pytest.raises(ValidationError, match="missing from fields"):
        BronzeNode.model_validate(_bronze(primary_key=["VBELN", "POSNR"]))


def test_key_field_true_outside_primary_key_is_rejected():
    fields = _bronze()["fields"]
    fields["MANDT"]["key_field"] = True
    with pytest.raises(ValidationError, match="not in primary_key"):
        BronzeNode.model_validate(_bronze(fields=fields))


def test_primary_key_member_without_key_field_is_rejected():
    fields = _bronze()["fields"]
    fields["VBELN"]["key_field"] = False
    with pytest.raises(ValidationError, match="without key_field"):
        BronzeNode.model_validate(_bronze(fields=fields))


def test_duplicate_field_alias_is_rejected_case_insensitively():
    """Compared lowercased: the ingestor's sanitizer lowercases aliases, so
    ``SALES`` and ``sales`` WOULD collide after sanitation. A validator that
    accepted what its own normalizer rejects would give false assurance."""
    fields = _bronze()["fields"]
    fields["MANDT"]["alias"] = "SALES_DOC"
    with pytest.raises(ValidationError, match="must be unique"):
        BronzeNode.model_validate(_bronze(fields=fields))


def test_all_violations_are_reported_at_once():
    """A corrupt bronze usually breaks several rules together. Reporting them one
    422 at a time turns a repair into a guess-and-retry loop, so the cross-field
    rules accumulate into a single error."""
    fields = _bronze()["fields"]
    fields["MANDT"]["alias"] = "sales_doc"  # alias collision
    fields["MANDT"]["key_field"] = True  # flagged but not in the key
    with pytest.raises(ValidationError) as exc:
        BronzeNode.model_validate(_bronze(primary_key=["VBELN", "VBELN", "POSNR"], fields=fields))
    msg = str(exc.value)
    assert "repeats columns" in msg
    assert "missing from fields" in msg
    assert "not in primary_key" in msg
    assert "must be unique" in msg


def test_wrong_layer_is_rejected():
    with pytest.raises(ValidationError):
        BronzeNode.model_validate(_bronze(layer="silver"))
