"""An in-process fake ServiceNow instance with fictional, seeded data.

It answers the same two endpoints the exporter uses:

    GET /api/now/table/<table>?sysparm_query=&sysparm_fields=&sysparm_limit=&sysparm_offset=
    GET /api/now/stats/<table>?sysparm_query=&sysparm_count=true

and it reproduces one real-world behaviour on purpose: **row-level ACLs**. Rows
the integration user may not read are dropped by the Table API but still counted
by the Aggregate API, exactly the kind of gap the reconciler must explain.
"""
from __future__ import annotations

import io
import json
import random
import urllib.parse
from datetime import datetime, timedelta

CATEGORIES = ["Accounts and Access", "Email and Calendar", "VPN and Remote Access", "Printing", "Laptops and Hardware",
              "Software Installation", "Local Admin Rights", "MFA and Passwordless", "Wi-Fi", "Meeting Rooms"]
CATALOG = ["Local admin rights (temporary)", "New software install", "Hardware request", "Shared mailbox access",
           "Distribution list change", "VPN access", "Group membership", "Meeting room support"]
CIS = ["Corporate laptop", "Exchange Online", "GlobalProtect VPN", "Print service", "Entra ID", "Wi-Fi network",
       "Teams Rooms", "Software Center"]
NAMES = ["Avery Abbott", "Blake Barlow", "Casey Carver", "Devon Dalton", "Emery Ellis", "Harper Hollis",
         "Jordan Jarvis", "Morgan Marsh", "Parker Pryor", "Quinn Quarles", "Reese Radley", "Rowan Sutter"]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _body(rnd: random.Random, title: str, category: str) -> str:
    steps = "".join(f"<li>Step {i}: {rnd.choice(['Open Settings', 'Sign in with your work account', 'Select the device', 'Restart the app', 'Confirm the prompt'])}.</li>"
                    for i in range(1, rnd.randint(3, 6)))
    pii = []
    if rnd.random() < 0.55:
        n = rnd.choice(NAMES)
        pii.append(f"<p>Questions? Contact {n} ({n.lower().replace(' ', '.')}@corp.example) on the service desk.</p>")
    if rnd.random() < 0.35:
        pii.append(f"<p>Urgent issues: call 416-555-{rnd.randint(1000, 9999)} (24/7).</p>")
    if rnd.random() < 0.30:
        pii.append(f"<p>If the portal fails, use the backup server at 10.{rnd.randint(1, 250)}.{rnd.randint(1, 250)}.{rnd.randint(1, 250)}.</p>")
    if rnd.random() < 0.45:
        pii.append(f'<p>See the <a href="https://intranet.corp.example/it/{rnd.randint(100, 999)}">internal procedure</a>.</p>')
    if rnd.random() < 0.25:
        pii.append('<p>Vendor guidance: <a href="https://support.microsoft.com/">Microsoft Support</a>.</p>')
    return f"<h2>{title}</h2><p>This article explains how to resolve common {category.lower()} issues.</p><ol>{steps}</ol>{''.join(pii)}"


def build_dataset(seed: int = 11, today: datetime = datetime(2026, 11, 1)) -> dict[str, list[dict]]:
    rnd = random.Random(seed)
    kb, sys_n = [], [0]

    def sid():
        sys_n[0] += 1
        return f"{sys_n[0]:032x}"

    # ---- knowledge articles: one row per version
    for i in range(1, 161):
        cat = CATEGORIES[(i - 1) % len(CATEGORIES)]
        title = f"{cat}: how to fix issue {i:03d}"
        versions = rnd.choice([1, 1, 1, 2, 2, 3])
        restricted = rnd.random() < 0.04
        fate = rnd.random()
        for v in range(1, versions + 1):
            latest = v == versions
            state = "published" if latest else "outdated"
            if latest and fate < 0.06:
                state = "retired"
            if latest and 0.06 <= fate < 0.09:
                state = "draft"
            updated = today - timedelta(days=rnd.randint(10, 900) // v)
            valid_to = "2100-01-01"
            if latest and state == "published" and fate > 0.96:
                valid_to = (today - timedelta(days=rnd.randint(5, 200))).strftime("%Y-%m-%d")   # expired
            kb.append({"sys_id": sid(), "number": f"KB{10000 + i:07d}", "version": f"{v}.0", "latest": str(latest).lower(),
                       "workflow_state": state, "valid_to": valid_to, "short_description": title, "kb_category": cat,
                       "text": _body(rnd, title, cat), "author": rnd.choice(NAMES), "sys_updated_on": updated.strftime("%Y-%m-%d %H:%M:%S"),
                       "_restricted": restricted})
    # ---- tickets
    tasks = []
    for n in range(1, 9001):
        is_req = rnd.random() < 0.55
        opened = today - timedelta(days=rnd.randint(1, 3 * 365), minutes=rnd.randint(0, 1440))
        if is_req:
            item = "Local admin rights (temporary)" if rnd.random() < 0.62 else rnd.choice(CATALOG[1:])
            tasks.append({"sys_id": sid(), "number": f"RITM{n:07d}", "sys_class_name": "sc_req_item", "cat_item": item,
                          "category": "Request", "cmdb_ci": "", "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S")})
        else:
            cat = rnd.choice(CATEGORIES)
            tasks.append({"sys_id": sid(), "number": f"INC{n:07d}", "sys_class_name": "incident", "cat_item": "",
                          "category": cat, "cmdb_ci": rnd.choice(CIS), "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S")})
    # ---- ticket-to-article links (m2m_kb_task)
    links = []
    linkable = [a for a in kb if a["latest"] == "true" or rnd.random() < 0.3]
    for t in rnd.sample(tasks, 700):
        a = rnd.choice(linkable)
        created = datetime.strptime(t["opened_at"], "%Y-%m-%d %H:%M:%S") + timedelta(hours=rnd.randint(1, 48))
        links.append({"sys_id": sid(), "task": t["sys_id"], "task_number": t["number"], "kb_knowledge": a["sys_id"],
                      "kb_number": a["number"], "sys_created_on": created.strftime("%Y-%m-%d %H:%M:%S"),
                      "_restricted": a["_restricted"]})
    for t in tasks:
        t["_restricted"] = False
    return {"kb_knowledge": kb, "task": tasks, "m2m_kb_task": links}


def _match(row: dict, query: str) -> bool:
    """Tiny subset of encoded-query syntax: field=value terms joined by ^."""
    if not query:
        return True
    for term in query.split("^"):
        if "!=" in term:
            f, v = term.split("!=", 1)
            if str(row.get(f, "")) == v:
                return False
        elif "=" in term:
            f, v = term.split("=", 1)
            if str(row.get(f, "")) != v:
                return False
    return True


class MockServiceNow:
    """Callable that behaves like urllib.request.urlopen for the two endpoints."""

    def __init__(self, data: dict[str, list[dict]] | None = None):
        self.data = data or build_dataset()
        self.requests: list = []

    def __call__(self, req):
        self.requests.append(req)
        if req.get_method() != "GET":
            raise PermissionError("mock instance is read-only")
        url = urllib.parse.urlparse(req.full_url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        parts = url.path.strip("/").split("/")
        api, table = parts[2], parts[3]
        rows = [r for r in self.data[table] if _match(r, q.get("sysparm_query", ""))]
        if api == "stats":
            return _Resp(json.dumps({"result": {"stats": {"count": str(len(rows))}}}).encode())
        visible = [r for r in rows if not r.get("_restricted")]          # row-level ACL
        fields = [f for f in q.get("sysparm_fields", "").split(",") if f]
        off, lim = int(q.get("sysparm_offset", 0)), int(q.get("sysparm_limit", 1000))
        page = [{k: v for k, v in r.items() if (not fields or k in fields) and not k.startswith("_")}
                for r in visible[off:off + lim]]
        return _Resp(json.dumps({"result": page}).encode())
