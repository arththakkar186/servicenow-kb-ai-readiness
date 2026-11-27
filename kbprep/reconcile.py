"""Explain any gap between the Aggregate API count and the rows the Table API returned.

Hypotheses are tested in order and each result is recorded, so the explanation
is evidence-based rather than a guess:

  1. Duplicates in the export          (same sys_id twice)
  2. Query/filter mismatch             (both calls used the same query string by construction)
  3. Deletions between the two calls   (re-count and compare)
  4. Row-level ACLs                    (what remains when 1-3 are ruled out; confirm by checking
                                        the missing records with an elevated, read-only account)
"""
from __future__ import annotations

from collections import Counter


def reconcile_table(table: str, rows: list[dict], aggregate_count: int, recount: int) -> dict:
    ids = Counter(r["sys_id"] for r in rows)
    duplicates = sum(c - 1 for c in ids.values() if c > 1)
    unique = len(ids)
    gap = aggregate_count - unique
    checks = [
        {"hypothesis": "duplicates in export", "result": "ruled out" if duplicates == 0 else f"{duplicates} duplicate rows"},
        {"hypothesis": "filter mismatch between calls", "result": "ruled out (identical sysparm_query on both calls)"},
        {"hypothesis": "deletions between calls", "result": "ruled out" if recount == aggregate_count
         else f"count changed {aggregate_count} -> {recount} during export"},
    ]
    if gap == 0:
        conclusion = "complete: Table API rows equal Aggregate API count"
    elif gap > 0 and duplicates == 0 and recount == aggregate_count:
        conclusion = (f"{gap} rows counted by the Aggregate API are not readable through the Table API: "
                      "consistent with row-level ACLs on the integration user. Confirm the specific records with an "
                      "elevated read-only account and decide whether they belong in the library")
        checks.append({"hypothesis": "row-level ACLs", "result": f"most likely: explains all {gap} rows"})
    else:
        conclusion = "unexplained: investigate before using these figures"
    return {"table": table, "table_api_rows": len(rows), "unique_rows": unique, "aggregate_count": aggregate_count,
            "gap": gap, "checks": checks, "conclusion": conclusion}
