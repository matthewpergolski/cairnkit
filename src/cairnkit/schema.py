"""The record format: field names, allowed values, and checks of one record."""

from __future__ import annotations

import re

from cairnkit.clock import is_time

KINDS = ("rule", "decision", "event", "trap", "preference", "lesson", "fact")
BASES = ("seen", "told", "guess")
STATUSES = ("active", "superseded", "expired", "wrong", "promoted")
SCOPES = ("long", "short")
RELS = ("related", "depends_on", "caused_by", "contradicts", "similar_to")
TYPES = ("fact", "change", "tombstone")
MAX_TEXT = 400
ID_RE = re.compile(r"^f-\d{8}-[0-9a-f]{4}$")
SOURCE_RE = re.compile(r"^(default$|[a-z][a-z0-9_-]*:\S)")
# The check that fails when a rule is broken: githook:commit-msg, lint:ruff:T201, ci:<job>.
ENFORCED_RE = re.compile(r"^[a-z][a-z0-9_-]*:\S{1,120}$")

FACT_REQUIRED = (
    "id",
    "kind",
    "text",
    "area",
    "happened_at",
    "learned_at",
    "source",
    "basis",
    "status",
    "writer",
)


def _check_links(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{field} must be a list"]
    errors = []
    for link in value:
        if not isinstance(link, dict) or set(link) != {"rel", "id"}:
            errors.append(f"{field}: each link must be {{rel, id}}")
        elif link["rel"] not in RELS:
            errors.append(f"{field}: rel {link['rel']!r} is not one of {', '.join(RELS)}")
    return errors


def _check_enforced(value: object) -> list[str]:
    if not isinstance(value, str) or not ENFORCED_RE.match(value):
        return [f"enforced_by {value!r} is not <type>:<value>, for example githook:commit-msg"]
    return []


def _check_fact(rec: dict) -> list[str]:
    errors = [f"missing field {name!r}" for name in FACT_REQUIRED if name not in rec]
    if "id" in rec and not ID_RE.match(str(rec["id"])):
        errors.append(f"id {rec['id']!r} is not f-YYYYMMDD-xxxx")
    if rec.get("kind", "fact") not in KINDS:
        errors.append(f"kind {rec['kind']!r} is not one of {', '.join(KINDS)}")
    if rec.get("basis", "seen") not in BASES:
        errors.append(f"basis {rec['basis']!r} is not one of {', '.join(BASES)}")
    if rec.get("status", "active") != "active":
        errors.append("a new fact must have status 'active'; use a change record")
    if rec.get("scope", "long") not in SCOPES:
        errors.append(f"scope {rec['scope']!r} is not one of {', '.join(SCOPES)}")
    text = rec.get("text", "")
    if not isinstance(text, str) or not text.strip():
        errors.append("text must be a non-empty string")
    elif len(text) > MAX_TEXT:
        errors.append(f"text has {len(text)} characters; the limit is {MAX_TEXT}")
    if "source" in rec and not SOURCE_RE.match(str(rec["source"])):
        errors.append(f"source {rec['source']!r} is not <kind>:<value> or default")
    for name in ("happened_at", "learned_at", "expires_at"):
        if name in rec and not is_time(rec[name]):
            errors.append(f"{name} {rec[name]!r} is not an ISO 8601 date or date-time")
    if "learned_at" in rec and is_time(rec["learned_at"]) and len(rec["learned_at"]) == 10:
        errors.append("learned_at needs a time with an offset")
    if "tags" in rec and not (
        isinstance(rec["tags"], list) and all(isinstance(t, str) for t in rec["tags"])
    ):
        errors.append("tags must be a list of strings")
    if "links" in rec:
        errors += _check_links(rec["links"], "links")
    if "enforced_by" in rec:
        errors += _check_enforced(rec["enforced_by"])
        if rec.get("kind") != "rule":
            errors.append("enforced_by is only for kind 'rule'")
    if "author" in rec and not (isinstance(rec["author"], str) and rec["author"].strip()):
        errors.append("author must be a non-empty string, for example agent:claude")
    if "pinned" in rec and not isinstance(rec["pinned"], bool):
        errors.append("pinned must be true or false")
    return errors


def _check_change(rec: dict) -> list[str]:
    errors = [f"missing field {n!r}" for n in ("id", "at", "writer") if n not in rec]
    if "at" in rec and not is_time(rec["at"]):
        errors.append(f"at {rec['at']!r} is not an ISO 8601 date-time")
    status = rec.get("status")
    if status is not None:
        if status not in STATUSES:
            errors.append(f"status {status!r} is not one of {', '.join(STATUSES)}")
        if not rec.get("reason"):
            errors.append("a status change needs a reason")
        if status == "superseded" and not rec.get("superseded_by"):
            errors.append("status 'superseded' needs superseded_by")
        if status == "promoted" and not rec.get("held_by"):
            errors.append("status 'promoted' needs held_by (the tracked file that holds it)")
    if rec.get("scope") is not None and rec["scope"] not in SCOPES:
        errors.append(f"scope {rec['scope']!r} is not one of {', '.join(SCOPES)}")
    if "add_links" in rec:
        errors += _check_links(rec["add_links"], "add_links")
    if rec.get("enforced_by") is not None:  # null clears it
        errors += _check_enforced(rec["enforced_by"])
    if not any(k in rec for k in ("status", "add_links", "scope", "enforced_by")):
        errors.append("a change must set status, scope, add_links or enforced_by")
    return errors


def _check_tombstone(rec: dict) -> list[str]:
    errors = [f"missing field {n!r}" for n in ("id", "at", "reason") if n not in rec]
    extra = set(rec) - {"type", "id", "at", "reason", "writer"}
    if extra:
        errors.append(f"a tombstone holds no content; remove {', '.join(sorted(extra))}")
    return errors


def validate_record(rec: object) -> list[str]:
    """Return the problems with one record. An empty list means it is well formed."""
    if not isinstance(rec, dict):
        return ["a record must be a JSON object"]
    kind = rec.get("type")
    if kind == "fact":
        return _check_fact(rec)
    if kind == "change":
        return _check_change(rec)
    if kind == "tombstone":
        return _check_tombstone(rec)
    return [f"type {kind!r} is not one of {', '.join(TYPES)}"]
