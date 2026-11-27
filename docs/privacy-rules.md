# Privacy Rules

Rules for any article sent to an AI tool or a shared AI library.

## 1. Minimise fields

Exactly five fields are published:

| Field | Source |
|---|---|
| `number` | `kb_knowledge.number` |
| `title` | `short_description` |
| `category` | `kb_category` |
| `body` | `text`, converted from HTML to plain text, then redacted |
| `last_updated` | `sys_updated_on` (date only) |

Never published: author, approvers, `sys_id`, workflow state, user criteria, attachments, comments, feedback.

## 2. Redact the body

| Type | Rule | Replacement |
|---|---|---|
| E-mail address | `name@domain.tld` | `[EMAIL]` |
| Phone number | North American formats, with or without +1 and separators | `[PHONE]` |
| IPv4 address | Four valid octets | `[IP ADDRESS]` |
| Internal link | Any URL whose host is, or is a subdomain of, a configured internal domain | `[INTERNAL LINK]` |
| Personal name | Names from the directory list, plus "Contact / Ask / Email / Call *First Last*" | `[NAME]` |

Public documentation links (for example `support.microsoft.com`) are kept, because they are useful and not sensitive.

## 3. Review and sign off

- `redaction_report.csv` has one row per article with counts by type and blank `reviewer` / `approved` columns.
- The reviewer samples articles, starting with the highest counts, and compares the source with the output.
- `redaction_log.csv` records each redaction's article, type and a 16-character SHA-256 prefix of the original value, so the log is not itself a PII store.
- The library is uploaded only after sign-off.

## 4. Known limits

- Names not in the directory and not after a trigger word can survive. Mitigations: reviewer sampling, and extending `known_names` with an export of display names (kept in memory only).
- Screenshots and attachments are excluded entirely, because text redaction cannot clean them.
- Article titles are not redacted. Title conventions should not include names.
