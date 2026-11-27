"""Field minimisation and PII redaction for articles leaving ServiceNow.

Only five fields go to the AI library: number, title, category, body, last_updated.
The body is converted from HTML to plain Markdown-style text, then scrubbed:

  email       ->  [EMAIL]
  phone       ->  [PHONE]
  IPv4        ->  [IP ADDRESS]
  internal URL->  [INTERNAL LINK]     (public vendor documentation links are kept)
  person name ->  [NAME]              (names from the directory list, plus "Contact <First Last>")

Every replacement is recorded with the article, type and original-value hash
(not the value), producing a review report for privacy sign-off.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

PUBLISHED_FIELDS = ("number", "title", "category", "body", "last_updated")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
URL = re.compile(r"https?://[^\s)\]]+")
CONTACT_NAME = re.compile(r"\b(?:[Cc]ontact|[Aa]sk|[Ee]mail|[Cc]all)\s+([A-Z][a-z]+ [A-Z][a-z]+)\b")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self._href, self._n = [], None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._n += 1
            self.out.append(f"\n{self._n}. ")
        elif tag in ("p", "br", "div"):
            self.out.append("\n")
        elif tag in ("h1", "h2", "h3"):
            self.out.append("\n## ")
        elif tag == "ol":
            self._n = 0
        elif tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.out.append(f" ({self._href})")
            self._href = None
        if tag in ("p", "h1", "h2", "h3", "ol", "ul"):
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html or "")
    text = "".join(p.out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@dataclass
class Redactor:
    internal_domains: tuple[str, ...]
    known_names: tuple[str, ...] = ()
    log: list[dict] = field(default_factory=list)

    def _note(self, number: str, kind: str, value: str):
        self.log.append({"article": number, "type": kind,
                         "value_sha256": hashlib.sha256(value.encode()).hexdigest()[:16]})

    def _is_internal(self, url: str) -> bool:
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        return any(host == d or host.endswith("." + d) for d in self.internal_domains)

    def scrub(self, number: str, text: str) -> str:
        def sub(pattern, kind, repl, s, keep=None):
            def f(m):
                if keep and keep(m.group(0)):
                    return m.group(0)
                self._note(number, kind, m.group(0))
                return repl
            return pattern.sub(f, s)

        text = sub(URL, "internal_link", "[INTERNAL LINK]", text, keep=lambda u: not self._is_internal(u))
        text = sub(EMAIL, "email", "[EMAIL]", text)
        text = sub(IPV4, "ip_address", "[IP ADDRESS]", text)
        text = sub(PHONE, "phone", "[PHONE]", text)
        for name in sorted(self.known_names, key=len, reverse=True):
            while name in text:
                self._note(number, "name", name)
                text = text.replace(name, "[NAME]", 1)

        def contact(m):
            self._note(number, "name", m.group(1))
            return m.group(0).replace(m.group(1), "[NAME]")
        return CONTACT_NAME.sub(contact, text)


def minimise(article: dict, redactor: Redactor) -> dict:
    body = redactor.scrub(article["number"], html_to_text(article["text"]))
    return {"number": article["number"], "title": article["short_description"], "category": article["kb_category"],
            "body": body, "last_updated": article["sys_updated_on"][:10]}
