"""Read-only export from the ServiceNow Table API, with checksummed raw files.

Every table is written exactly as received to raw/<table>.json, and its SHA-256
is recorded. All later figures are computed from these raw files, never from
live queries, so every number in the report can be re-derived and verified.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

TABLES = {
    "kb_knowledge": ["sys_id", "number", "version", "latest", "workflow_state", "valid_to", "short_description",
                     "kb_category", "text", "author", "sys_updated_on"],
    "task": ["sys_id", "number", "sys_class_name", "cat_item", "category", "cmdb_ci", "opened_at"],
    "m2m_kb_task": ["sys_id", "task", "task_number", "kb_knowledge", "kb_number", "sys_created_on"],
}


class SnClient:
    def __init__(self, instance: str, token: str | None = None, opener: Callable | None = None, page_size: int = 1000):
        self.base = f"https://{instance}.service-now.com"
        self.token = token if token is not None else os.environ.get("SN_TOKEN", "")
        self._open = opener or urllib.request.urlopen
        self.page_size = page_size

    def _get(self, path: str, params: dict) -> dict:
        req = urllib.request.Request(f"{self.base}{path}?{urllib.parse.urlencode(params)}", method="GET",
                                     headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}"})
        with self._open(req) as r:
            return json.loads(r.read().decode())

    def rows(self, table: str, fields: list[str], query: str = "") -> list[dict]:
        out, off = [], 0
        while True:
            page = self._get(f"/api/now/table/{table}", {"sysparm_query": query, "sysparm_fields": ",".join(fields),
                                                         "sysparm_limit": self.page_size, "sysparm_offset": off})["result"]
            out += page
            if len(page) < self.page_size:
                return out
            off += self.page_size

    def count(self, table: str, query: str = "") -> int:
        return int(self._get(f"/api/now/stats/{table}", {"sysparm_query": query, "sysparm_count": "true"})["result"]["stats"]["count"])


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_all(client: SnClient, out: Path) -> dict:
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for table, fields in TABLES.items():
        rows = client.rows(table, fields)
        blob = json.dumps(rows, indent=1, sort_keys=True).encode()
        (raw / f"{table}.json").write_bytes(blob)
        manifest[table] = {"rows": len(rows), "aggregate_count": client.count(table), "sha256": sha256(blob)}
    (raw / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_raw(out: Path, verify: bool = True) -> dict[str, list[dict]]:
    raw = out / "raw"
    manifest = json.loads((raw / "manifest.json").read_text())
    data = {}
    for table, meta in manifest.items():
        blob = (raw / f"{table}.json").read_bytes()
        if verify and sha256(blob) != meta["sha256"]:
            raise ValueError(f"raw/{table}.json does not match its recorded checksum; re-export before reporting")
        data[table] = json.loads(blob)
    return data
