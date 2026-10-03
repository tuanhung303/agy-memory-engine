"""Evidence tags for memory writes (Kai, 2026-10-03).

Every stored fact, learning and episode narrative starts with one header line:

    [verified | 2026-10-03T21:40+07:00 | by claude-opus-5-5 | evidence: gcloud run services describe]

The writer picks the tag; the server validates it and builds the header, so a
reader always sees how far to trust the entry and when it was true.
Policy: ~/.gemini/config/SHARED-MEMORY.md
"""

import re
from datetime import datetime, timedelta, timezone

EVIDENCE_TAGS = (
    "executed",
    "verified",
    "decided",
    "client-stated",
    "inferred",
    "assumed",
    "speculated",
    "planned",
)
NEEDS_EVIDENCE = frozenset({"executed", "verified"})
KAI_TZ = timezone(timedelta(hours=7))

_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z))?$")
_HEADER_RE = re.compile(
    r"^\[(?P<tag>[a-z-]+) \| (?P<as_of>\S+) \| by (?P<by>[^|\]]+?)(?: \| evidence: (?P<evidence>.*))?\]$"
)

FORMAT_HINT = (
    "Pass tag (one of: " + ", ".join(EVIDENCE_TAGS) + "); "
    "evidence for executed and verified (commit SHA, revision, job ID, query or file:line); "
    "as_of like 2026-10-03T21:40+07:00 or 2026-10-03 (default: now, UTC+7); "
    "by = agent and model. Policy: ~/.gemini/config/SHARED-MEMORY.md"
)

READING_RULE = (
    "Each entry starts with [tag | as_of | by | evidence]. decided binds until superseded. "
    "executed and verified are true as of as_of; re-check one older than 7 days before a "
    "production or shared-state action. client-stated is the client's claim, not our finding. "
    "inferred, speculated, planned and untagged entries are leads: verify before acting."
)


class EvidenceTagError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(KAI_TZ).isoformat(timespec="minutes")


def _clean(value: str) -> str:
    # One header line only: no newlines, no closing bracket in free text.
    return " ".join((value or "").split()).replace("]", ")")


def build_header(tag: str, evidence: str = "", as_of: str = "", by: str = "") -> str:
    norm_tag = (tag or "").strip().lower()
    if norm_tag not in EVIDENCE_TAGS:
        raise EvidenceTagError(f"Memory write rejected: unknown or missing tag '{tag}'. {FORMAT_HINT}")
    clean_evidence = _clean(evidence)
    if norm_tag in NEEDS_EVIDENCE and not clean_evidence:
        raise EvidenceTagError(f"Memory write rejected: tag '{norm_tag}' needs evidence. {FORMAT_HINT}")
    clean_as_of = (as_of or "").strip() or now_iso()
    if not _AS_OF_RE.match(clean_as_of):
        raise EvidenceTagError(f"Memory write rejected: as_of '{as_of}' is not ISO 8601 with offset. {FORMAT_HINT}")
    clean_by = _clean(by).replace("|", "/") or "unspecified"
    header = f"[{norm_tag} | {clean_as_of} | by {clean_by}"
    if clean_evidence:
        header += f" | evidence: {clean_evidence}"
    return header + "]"


def parse_header(text: str):
    """Return the header fields as a dict, or None when the text has no valid header."""
    first_line = (text or "").split("\n", 1)[0].strip()
    match = _HEADER_RE.match(first_line)
    if not match or match.group("tag") not in EVIDENCE_TAGS:
        return None
    return match.groupdict()


def strip_header(text: str) -> str:
    if parse_header(text) is None:
        return (text or "").strip()
    parts = (text or "").strip().split("\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def apply_header(text: str, tag: str, evidence: str = "", as_of: str = "", by: str = "") -> str:
    body = strip_header(text)
    if not body:
        raise EvidenceTagError("Memory write rejected: the entry text is empty after the header.")
    return build_header(tag, evidence, as_of, by) + "\n" + body


def tag_keywords(keywords: str, tag: str) -> str:
    token = f"tag:{(tag or '').strip().lower()}"
    words = (keywords or "").split()
    if token not in words:
        words.append(token)
    return " ".join(words)
