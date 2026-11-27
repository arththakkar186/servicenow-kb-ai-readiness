"""End-to-end pipeline.

    python3 -m kbprep run --out out/                 # against the built-in fictional mock instance
    python3 -m kbprep run --out out/ --instance acme # against a real instance (read-only, SN_TOKEN)

Steps: export (raw + SHA-256) -> reconcile counts -> current versions -> minimise
and redact -> rank -> write library files and reports. Every figure in
report.md is rebuilt from the checksummed raw files.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import __version__
from .export import SnClient, export_all, load_raw
from .mock_instance import NAMES, MockServiceNow
from .rank import demand_groups, link_recency, rank_articles, request_mix
from .reconcile import reconcile_table
from .redact import PUBLISHED_FIELDS, Redactor, minimise
from .versions import current_articles, summary


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run(out: Path, client: SnClient, today: datetime, internal_domains: tuple[str, ...], known_names: tuple[str, ...]) -> dict:
    manifest = export_all(client, out)
    raw = load_raw(out)
    recon = [reconcile_table(t, raw[t], m["aggregate_count"], client.count(t)) for t, m in manifest.items()]

    kept, dropped = current_articles(raw["kb_knowledge"], today.date())
    vsum = summary(kept, dropped)

    red = Redactor(internal_domains, known_names)
    library = [minimise(a, red) for a in kept]
    lib_dir = out / "library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    for doc in library:
        front = "\n".join(f"{k}: {json.dumps(doc[k])}" for k in PUBLISHED_FIELDS if k != "body")
        (lib_dir / f"{doc['number']}.md").write_text(f"---\n{front}\n---\n\n{doc['body']}\n")

    by_type = Counter(e["type"] for e in red.log)
    per_article = Counter(e["article"] for e in red.log)
    write_csv(out / "redaction_report.csv", [
        {"article": a["number"], "title": a["short_description"], "redactions": per_article[a["number"]],
         **{t: sum(1 for e in red.log if e["article"] == a["number"] and e["type"] == t)
            for t in ("email", "phone", "ip_address", "internal_link", "name")},
         "reviewer": "", "approved": ""} for a in kept])
    write_csv(out / "redaction_log.csv", red.log)
    write_csv(out / "dropped_versions.csv", [{"number": d["number"], "version": d["version"],
                                              "state": d["workflow_state"], "reason": d["_drop_reason"]} for d in dropped])

    ranking = rank_articles(kept, raw["m2m_kb_task"], today)
    groups = demand_groups(raw["task"], raw["m2m_kb_task"])
    mix = request_mix(raw["task"], today)
    recency = link_recency(raw["m2m_kb_task"], today)
    write_csv(out / "article_ranking.csv", ranking)
    write_csv(out / "demand_groups.csv", groups)

    figures = {"tool_version": __version__, "as_of": today.strftime("%Y-%m-%d"), "raw_manifest": manifest,
               "reconciliation": recon, "versions": vsum,
               "redactions": {"total": len(red.log), "by_type": dict(by_type), "articles_with_redactions": len(per_article)},
               "published_fields": list(PUBLISHED_FIELDS), "request_mix": mix, "link_recency": recency,
               "demand_groups": len(groups)}
    (out / "figures.json").write_text(json.dumps(figures, indent=2) + "\n")
    (out / "report.md").write_text(render_report(figures, ranking, groups))
    return figures


def render_report(f: dict, ranking: list[dict], groups: list[dict]) -> str:
    v, r, m, lr = f["versions"], f["redactions"], f["request_mix"], f["link_recency"]
    L = [f"# Knowledge library readiness report ({f['as_of']})", "",
         "All figures are rebuilt from the checksummed raw exports in `raw/` (see `figures.json`).", "",
         "## 1. Export and completeness", "", "| Table | Table API rows | Aggregate count | Gap | Conclusion |", "|---|---:|---:|---:|---|"]
    for x in f["reconciliation"]:
        L.append(f"| {x['table']} | {x['table_api_rows']} | {x['aggregate_count']} | {x['gap']} | {x['conclusion']} |")
    L += ["", "## 2. Versions", "",
          f"- Exported article rows: **{v['exported_rows']}**",
          f"- Current articles kept: **{v['current_articles']}**",
          f"- Dropped: **{v['dropped']}**: " + ", ".join(f"{k} {n}" for k, n in v["dropped_by_reason"].items()),
          "", "## 3. Privacy", "",
          f"- Published fields per article: {', '.join(f['published_fields'])} ({len(f['published_fields'])})",
          f"- Redactions: **{r['total']}** across {r['articles_with_redactions']} articles: "
          + ", ".join(f"{k} {n}" for k, n in sorted(r["by_type"].items())),
          "- Per-article counts for sign-off: `redaction_report.csv`", "",
          "## 4. Demand", "",
          f"- Service requests: {m['requests_total']} in total, {m['requests_last_12m']} in the last 12 months.",
          f"- Top request: **{m['top_item']}** = **{m['top_item_share_pct']}%** of all requests "
          f"({m['top_item_last_12m']} in the last 12 months): the largest self-service / automation opportunity.",
          f"- Ticket-to-article links: {lr['links_total']}, of which only **{lr['links_last_12m']}** "
          f"({lr['links_last_12m_pct']}%) were made in the last 12 months. Compare with the share of tickets opened in "
          "the same window to see whether agents attach articles less often than before.",
          "", "### Top 10 articles by linked tickets", "", "| # | Article | Category | Linked | Last 12 m |", "|---:|---|---|---:|---:|"]
    for i, a in enumerate(ranking[:10], 1):
        L.append(f"| {i} | {a['number']} {a['title']} | {a['category']} | {a['linked_tickets']} | {a['linked_last_12m']} |")
    L += ["", "### Highest-volume groups with the lowest article coverage", "", "| Dimension | Group | Tickets | With article | Coverage |", "|---|---|---:|---:|---:|"]
    for g in sorted(groups, key=lambda g: (g["article_coverage_pct"], -g["tickets"]))[:8]:
        L.append(f"| {g['dimension']} | {g['group']} | {g['tickets']} | {g['tickets_with_article']} | {g['article_coverage_pct']}% |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kbprep")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("--out", required=True)
    s.add_argument("--instance", help="real ServiceNow instance name; omit to use the fictional mock")
    s.add_argument("--as-of", default="2026-11-01")
    s.add_argument("--internal-domain", action="append", default=None,
                   help="domain whose links are internal (repeatable); default corp.example and service-now.com")
    a = p.parse_args(argv)
    today = datetime.strptime(a.as_of, "%Y-%m-%d")
    domains = tuple(a.internal_domain or ["corp.example", "service-now.com"])
    if a.instance:
        client, names = SnClient(a.instance), ()
    else:
        client, names = SnClient("mock", token="", opener=MockServiceNow()), tuple(NAMES)
    f = run(Path(a.out), client, today, domains, names)
    v = f["versions"]
    print(f"Exported {v['exported_rows']} article rows -> {v['current_articles']} current articles "
          f"({v['dropped']} dropped). Redactions: {f['redactions']['total']}.")
    for x in f["reconciliation"]:
        print(f"  {x['table']}: {x['table_api_rows']} rows vs {x['aggregate_count']} counted -> {x['conclusion'][:70]}")
    print(f"Top request '{f['request_mix']['top_item']}' = {f['request_mix']['top_item_share_pct']}% of requests. Report: {a.out}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
