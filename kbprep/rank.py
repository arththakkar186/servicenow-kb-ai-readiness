"""Rank articles by real demand and find self-service opportunities.

* Article ranking: tickets linked to each current article (all time and last 12 months).
* Demand groups: tickets grouped by incident category, configuration item (CI) and
  catalog item, with how many of those tickets ever had an article attached.
* Request mix: share of service requests by catalog item; a dominant item is a strong
  self-service or automation candidate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta


def _dt(s: str) -> datetime:
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def rank_articles(current: list[dict], links: list[dict], today: datetime) -> list[dict]:
    year_ago = today - timedelta(days=365)
    numbers = {a["number"] for a in current}
    total, recent, last = Counter(), Counter(), {}
    for l in links:
        n = l["kb_number"]
        if n not in numbers:
            continue      # link to a superseded / retired version: counts toward the version, not the library
        total[n] += 1
        if _dt(l["sys_created_on"]) >= year_ago:
            recent[n] += 1
        last[n] = max(last.get(n, ""), l["sys_created_on"])
    rows = [{"number": a["number"], "title": a["short_description"], "category": a["kb_category"],
             "linked_tickets": total[a["number"]], "linked_last_12m": recent[a["number"]],
             "last_linked": last.get(a["number"], "")[:10]} for a in current]
    return sorted(rows, key=lambda r: (-r["linked_tickets"], -r["linked_last_12m"], r["number"]))


def demand_groups(tasks: list[dict], links: list[dict]) -> list[dict]:
    linked = {l["task"] for l in links}
    groups: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for t in tasks:
        keys = []
        if t["sys_class_name"] == "incident":
            keys += [("category", t["category"]), ("ci", t["cmdb_ci"])]
        else:
            keys.append(("catalog_item", t["cat_item"]))
        for k in keys:
            if not k[1]:
                continue
            groups[k][0] += 1
            groups[k][1] += t["sys_id"] in linked
    out = [{"dimension": d, "group": g, "tickets": n, "tickets_with_article": w,
            "article_coverage_pct": round(100 * w / n, 1) if n else 0.0} for (d, g), (n, w) in groups.items()]
    return sorted(out, key=lambda r: -r["tickets"])


def request_mix(tasks: list[dict], today: datetime) -> dict:
    year_ago = today - timedelta(days=365)
    reqs = [t for t in tasks if t["sys_class_name"] == "sc_req_item"]
    last_year = [t for t in reqs if _dt(t["opened_at"]) >= year_ago]
    mix = Counter(t["cat_item"] for t in reqs)
    top, n = mix.most_common(1)[0] if mix else ("", 0)
    return {"requests_total": len(reqs), "requests_last_12m": len(last_year), "top_item": top,
            "top_item_share_pct": round(100 * n / len(reqs), 1) if reqs else 0.0,
            "top_item_last_12m": sum(1 for t in last_year if t["cat_item"] == top),
            "by_item": dict(mix.most_common())}


def link_recency(links: list[dict], today: datetime) -> dict:
    year_ago = today - timedelta(days=365)
    recent = sum(1 for l in links if _dt(l["sys_created_on"]) >= year_ago)
    return {"links_total": len(links), "links_last_12m": recent,
            "links_last_12m_pct": round(100 * recent / len(links), 1) if links else 0.0}
