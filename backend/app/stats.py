"""Per-role workload aggregation for the dashboard.

Each role's progress is derived from its primary status field, and every record
is bucketed into exactly one of: done / incoming / pending. A record that has no
value yet for a role's status counts as *pending* for that role (it hasn't
reached that team). Buckets therefore always sum to the record total.
"""

from __future__ import annotations

from app.models import Record


# Stands in for an empty status in the per-value breakdown. Not filterable on the
# records list (that matches substrings), so the UI leaves these rows unlinked.
BLANK_LABEL = "(not set)"


def _bucket_compliance(v: str) -> str:
    """SPA Status arrives in two vocabularies: the prototype's enum, and the one
    the SOMA3 workbook actually uses ("Not needed" / "Completed" / "No Copy" /
    "Lacking Copy"). Both are bucketed, so the donut works whichever a file
    speaks. "Not needed" is done: a unit that needs no SPA has nothing left for
    compliance to do."""
    lv = v.lower()
    if lv in {"signed", "released", "notarized", "completed", "complete", "not needed"}:
        return "done"
    if lv in {"for signing", "pending preparation"}:
        return "incoming"
    return "pending"


def _bucket_scanning(v: str) -> str:
    lv = v.lower()
    if lv.startswith("scanned"):
        return "done"
    if lv == "pending scanning":
        return "incoming"
    return "pending"


def _bucket_notary(v: str) -> str:
    lv = v.lower()
    if "notariz" in lv or "endors" in lv:
        return "done"
    if "for" in lv or "pending" in lv or "sent" in lv:
        return "incoming"
    return "pending"


def _bucket_filing(v: str) -> str:
    if v in {"On File - Complete", "On File - W/ RDU", "Archived"}:
        return "done"
    if v in {"For Filing", "For Archiving"}:
        return "incoming"
    return "pending"


# role key -> (display label, status field key, bucketing fn)
ROLE_SPECS = [
    ("document_compliance", "Document Compliance", "spa_status", _bucket_compliance),
    ("scanning", "Scanning", "docket_scanning_status", _bucket_scanning),
    ("notary", "Notary", "notary_status", _bucket_notary),
    ("filing", "Filing", "file_status", _bucket_filing),
]


def compute_stats(records: list[Record]) -> dict:
    total = len(records)
    roles = []
    for role_key, label, field_key, fn in ROLE_SPECS:
        counts = {"done": 0, "incoming": 0, "pending": 0}
        # The raw status values behind each bucket, so the dashboard can explain
        # *why* a bucket is the size it is. Blank reads as BLANK_LABEL — a real
        # answer for "pending", which is mostly records that never reached the team.
        seen: dict[str, dict[str, int]] = {"done": {}, "incoming": {}, "pending": {}}
        for r in records:
            val = str((r.data or {}).get(field_key) or "").strip()
            bucket = fn(val)
            counts[bucket] += 1
            label_v = val or BLANK_LABEL
            seen[bucket][label_v] = seen[bucket].get(label_v, 0) + 1
        done_pct = round(100 * counts["done"] / total, 1) if total else 0.0
        roles.append(
            {
                "role": role_key,
                "label": label,
                "field": field_key,
                "total": total,
                "done": counts["done"],
                "incoming": counts["incoming"],
                "pending": counts["pending"],
                "done_pct": done_pct,
                # Biggest first — the client renders these in order.
                "breakdown": {
                    b: [
                        {"value": v, "n": n}
                        for v, n in sorted(vals.items(), key=lambda kv: -kv[1])
                    ]
                    for b, vals in seen.items()
                },
            }
        )

    # overall unit-status distribution (informational)
    unit_status: dict[str, int] = {}
    for r in records:
        s = (r.data or {}).get("unit_status") or "—"
        unit_status[s] = unit_status.get(s, 0) + 1

    # records currently counting toward the 90-day fallout/cancelled archive
    # window (Record.archive_countdown_days), soonest/most-overdue first.
    soon_to_archive = sorted(
        (
            {
                "id": r.id,
                "unit_code": r.unit_code,
                "company": (r.data or {}).get("company"),
                "arch_accounts_status": (r.data or {}).get("arch_accounts_status"),
                "days": r.archive_countdown_days,
            }
            for r in records
            if r.archive_countdown_days is not None
        ),
        key=lambda x: x["days"],
    )

    return {
        "total_records": total,
        "roles": roles,
        "unit_status": unit_status,
        "soon_to_archive": soon_to_archive,
    }
