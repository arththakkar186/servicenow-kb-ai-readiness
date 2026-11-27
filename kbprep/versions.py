"""Keep exactly one current version per article.

An article number can have several rows (versions). A row is kept only if it is
the latest version, published, and not past its valid-to date. Everything else
is dropped with a reason, so the reduction from exported rows to current
articles is fully explained.
"""
from __future__ import annotations

from collections import Counter
from datetime import date


def current_articles(rows: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for r in rows:
        reason = None
        if r["latest"] != "true":
            reason = "superseded by a newer version"
        elif r["workflow_state"] == "retired":
            reason = "retired"
        elif r["workflow_state"] != "published":
            reason = f"not published ({r['workflow_state']})"
        elif r["valid_to"] and r["valid_to"] < today.isoformat():
            reason = f"expired (valid to {r['valid_to']})"
        (dropped if reason else kept).append({**r, "_drop_reason": reason} if reason else r)
    dupes = [n for n, c in Counter(r["number"] for r in kept).items() if c > 1]
    if dupes:
        raise ValueError(f"more than one current version for {dupes[:5]}")
    return kept, dropped


def summary(kept: list[dict], dropped: list[dict]) -> dict:
    return {"exported_rows": len(kept) + len(dropped), "current_articles": len(kept),
            "dropped": len(dropped), "dropped_by_reason": dict(Counter(
                d["_drop_reason"].split(" (")[0] for d in dropped).most_common())}
