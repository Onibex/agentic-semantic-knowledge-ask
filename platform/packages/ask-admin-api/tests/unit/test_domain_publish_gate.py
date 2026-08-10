"""Iter 5 (CH-5) domain bulk-publish gate — `_needs_publish` (pure logic)."""

from __future__ import annotations

from ask_admin_api.models.data_products import DataProductLifecycle, PublishRecord
from ask_admin_api.routers.business_domains import _needs_publish


def _rec(sha: str, version: int = 1) -> PublishRecord:
    return PublishRecord(version=version, sha=sha, at="2026-06-09T00:00:00Z", by="t@x.com")


def _lc(main_sha: str, dev=None, prod=None) -> DataProductLifecycle:
    return DataProductLifecycle(
        entity_id="e", main_sha=main_sha, dev_published=dev, prod_published=prod
    )


def test_dev_needs_when_never_published():
    assert _needs_publish(None, "dev")[0] is True
    assert _needs_publish(_lc("abc"), "dev")[0] is True  # dev_published is None


def test_dev_skips_when_current():
    needs, reason = _needs_publish(_lc("abc", dev=_rec("abc")), "dev")
    assert needs is False
    assert "up to date" in (reason or "")


def test_dev_needs_after_edit_since_release():
    # main advanced past the last dev publish → In Review → needs dev.
    assert _needs_publish(_lc("NEW", dev=_rec("OLD")), "dev")[0] is True


def test_prod_skips_when_no_dev():
    assert _needs_publish(None, "prod")[0] is False
    needs, reason = _needs_publish(_lc("abc"), "prod")  # dev None
    assert needs is False
    assert "dev" in (reason or "")


def test_prod_needs_when_dev_ahead_of_prod():
    lc = _lc("abc", dev=_rec("abc", 2))  # prod None
    assert _needs_publish(lc, "prod")[0] is True


def test_prod_skips_when_up_to_date_with_dev():
    lc = _lc("same", dev=_rec("same", 2), prod=_rec("same", 2))
    needs, reason = _needs_publish(lc, "prod")
    assert needs is False
    assert "up to date" in (reason or "")
