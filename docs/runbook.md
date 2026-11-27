# Runbook

## Prerequisites

- A ServiceNow integration user with **read-only** roles on `kb_knowledge`, `task` (or `incident` + `sc_req_item`) and `m2m_kb_task`.
- An OAuth token for that user in `SN_TOKEN`, from the secrets manager.
- The list of internal domains (for link redaction).

## Run

```bash
python3 -m kbprep run --out out/$(date +%Y%m%d) --instance <instance> \
    --internal-domain corp.example --internal-domain service-now.com --as-of $(date +%Y-%m-%d)
```

## Check

| Check | Where | Action if it fails |
|---|---|---|
| Every table's gap is 0 or explained | `report.md` §1 | Investigate with an elevated read-only account before publishing |
| Dropped versions look right | `dropped_versions.csv` | Ask article owners about anything unexpected (for example an expired article that is still needed) |
| Redaction sample | `redaction_report.csv`, top 20 by count + 10 random | Fix rules, re-run, re-sample |
| No PII in `library/` | Search for `@`, digits patterns, internal hosts | Add rules, re-run |

## Publish

1. Reviewer fills in `reviewer` / `approved` in `redaction_report.csv`.
2. Upload `library/*.md` to the knowledge library (for example a SharePoint document library indexed by the AI assistant), replacing the previous set.
3. Archive the whole `out/<date>/` folder (raw + manifest + reports) as the evidence of what was published.

## Refresh

Monthly, or after a large knowledge update. Compare `figures.json` with the previous run to see drift (new articles, newly expired ones, ranking changes).
