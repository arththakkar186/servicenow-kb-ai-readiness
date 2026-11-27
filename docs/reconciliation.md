# Count Reconciliation Method

## Problem

Two ServiceNow APIs can disagree about how many rows match the same query:

- **Table API** (`/api/now/table/<t>`) returns only rows that pass the caller's **row-level ACLs**.
- **Aggregate API** (`/api/now/stats/<t>?sysparm_count=true`) can count rows the caller cannot read.

If a report uses one number and the export uses the other, figures stop adding up, and nobody can say why.

## Method (`reconcile.py`)

For each table, after export:

| # | Hypothesis | Test | Ruled out when |
|---|---|---|---|
| 1 | Duplicates in the export (paging overlap) | Count repeated `sys_id`s | 0 duplicates |
| 2 | Different filters on the two calls | Both calls are built from the same `sysparm_query` string | Always, by construction |
| 3 | Records deleted or created during the export | Count again after the export | Re-count = first count |
| 4 | Row-level ACLs | What remains once 1-3 are ruled out | Confirm by checking the missing range with an elevated read-only account |

Output per table: rows, unique rows, aggregate count, gap, each hypothesis result, and a conclusion. A gap that 1-4 cannot
explain is reported as **unexplained**, and the figures should not be used until it is resolved.

## Example (mock instance)

| Table | Table API | Aggregate | Gap | Conclusion |
|---|---:|---:|---:|---|
| kb_knowledge | 260 | 278 | 18 | Row-level ACLs (restricted HR articles in the mock) |
| task | 9000 | 9000 | 0 | Complete |
| m2m_kb_task | 661 | 700 | 39 | Row-level ACLs (links to restricted articles inherit the restriction) |

## Then: rebuild every figure from raw

Once the population is understood, every figure (article counts, link counts, rankings) is recomputed from the
checksummed raw files. `load_raw()` refuses to run if any file no longer matches its recorded SHA-256.
