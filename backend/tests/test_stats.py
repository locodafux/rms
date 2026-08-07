from __future__ import annotations

from app.models import Record
from app.stats import BLANK_LABEL, compute_stats


def _rec(**data) -> Record:
    """An unsaved Record — compute_stats is pure, it never touches the session."""
    return Record(unit_code="U", data=data)


def test_breakdown_explains_each_bucket():
    records = [
        _rec(docket_scanning_status="Scanned - Complete"),
        _rec(docket_scanning_status="Scanned - Complete"),
        _rec(docket_scanning_status="Scanned - w/ RDU"),
        _rec(docket_scanning_status="Pending Scanning"),
        _rec(docket_scanning_status="No Docket/CPAs yet"),
        _rec(),  # never reached the team
    ]
    scanning = next(r for r in compute_stats(records)["roles"] if r["role"] == "scanning")

    assert (scanning["done"], scanning["incoming"], scanning["pending"]) == (3, 1, 2)

    # Values are grouped under the bucket they land in, biggest first.
    assert scanning["breakdown"]["done"] == [
        {"value": "Scanned - Complete", "n": 2},
        {"value": "Scanned - w/ RDU", "n": 1},
    ]
    assert scanning["breakdown"]["incoming"] == [{"value": "Pending Scanning", "n": 1}]
    assert {e["value"] for e in scanning["breakdown"]["pending"]} == {
        "No Docket/CPAs yet",
        BLANK_LABEL,
    }

    # Every bucket's breakdown must account for exactly that bucket's count, or
    # the drill-down would show numbers the card disagrees with.
    for bucket in ("done", "incoming", "pending"):
        assert sum(e["n"] for e in scanning["breakdown"][bucket]) == scanning[bucket]


def test_breakdown_covers_every_role_and_totals_match():
    records = [_rec(spa_status="Signed", notary_status="Notarized", file_status="For Filing")]
    for role in compute_stats(records)["roles"]:
        counted = sum(e["n"] for b in role["breakdown"].values() for e in b)
        assert counted == role["total"] == 1, role["role"]


def test_compliance_buckets_the_workbooks_own_vocabulary():
    """The real SOMA3 file says "Completed"/"Not needed", not "Signed" — both
    vocabularies have to land in the same buckets or the donut reads 0%."""
    records = [
        _rec(spa_status="Completed"),
        _rec(spa_status="Not needed"),   # nothing left for compliance to do
        _rec(spa_status="No Copy"),
        _rec(spa_status="Signed"),       # prototype vocabulary still works
        _rec(spa_status=""),
    ]
    compliance = compute_stats(records)["roles"][0]
    assert compliance["role"] == "document_compliance"
    assert compliance["done"] == 3
    assert compliance["pending"] == 2
