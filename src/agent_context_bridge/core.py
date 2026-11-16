"""Core data structures and storage engine for Agent Context Bridge."""

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from agent_context_bridge.utils import estimate_tokens, atomic_write, sanitize_agent_name


# Hardening limits (step 2): shared validation caps.
MAX_LIST_LIMIT = 1000
MAX_AGENT_LEN = 64
MAX_TOPIC_LEN = 200
MAX_SUMMARY_LEN = 2000
MAX_DETAILS_LEN = 20000
MAX_TAGS = 20
MAX_TAG_LEN = 50

#: Search page size cap (§2.1: 1..100).
MAX_SEARCH_LIMIT = 100

#: Agent targets reported by ``status`` (§2.2).
STATUS_TARGETS = ("hermes", "claude", "opencode", "codex")


def _secure_chmod(path: Path, mode: int) -> None:
    """Best-effort chmod (M1: 0o700 dir, 0o600 files). Never raises."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _validate_record_fields(agent, topic, summary, details, tags) -> None:
    """Validate record fields; raise ValueError with a clear message on violation."""
    if agent is None or not str(agent).strip():
        raise ValueError("agent must not be empty.")
    if len(str(agent).strip()) > MAX_AGENT_LEN:
        raise ValueError(f"agent must be at most {MAX_AGENT_LEN} characters.")
    if topic is None or not str(topic).strip():
        raise ValueError("topic must not be empty.")
    if len(str(topic).strip()) > MAX_TOPIC_LEN:
        raise ValueError(f"topic must be at most {MAX_TOPIC_LEN} characters.")
    if summary is None or not str(summary).strip():
        raise ValueError("summary must not be empty.")
    if len(str(summary).strip()) > MAX_SUMMARY_LEN:
        raise ValueError(f"summary must be at most {MAX_SUMMARY_LEN} characters.")
    if details is not None and len(str(details)) > MAX_DETAILS_LEN:
        raise ValueError(f"details must be at most {MAX_DETAILS_LEN} characters.")
    if tags is not None:
        tag_list = list(tags)
        if len(tag_list) > MAX_TAGS:
            raise ValueError(f"at most {MAX_TAGS} tags allowed (got {len(tag_list)}).")
        for t in tag_list:
            if len(str(t)) > MAX_TAG_LEN:
                raise ValueError(f"each tag must be at most {MAX_TAG_LEN} characters (got {t!r}).")


def _package_version() -> str:
    """Resolve the package version without hardcoding (lazy: avoids import cycle).

    Prefers installed dist metadata, falls back to ``__version__``.
    """
    try:
        from importlib.metadata import version, PackageNotFoundError

        try:
            return version("agent-context-bridge")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    from agent_context_bridge import __version__

    return __version__


def record_id(record: "ContextRecord") -> str:
    """Stable 6-hex short id for display + JSON (records predate stored ids)."""
    basis = f"{record.timestamp}|{record.agent}|{record.topic}|{record.summary}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:6]


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (tolerates trailing ``Z``); None if unparsable."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _to_zulu(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with ``Z`` suffix."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def record_to_search_dict(record: "ContextRecord") -> Dict[str, Any]:
    """JSON payload for one search hit (§3.2)."""
    return {
        "id": record_id(record),
        "agent": record.agent,
        "topic": record.topic,
        "summary": record.summary,
        "details": record.details,
        "tags": list(record.tags or []),
        "created_at": record.timestamp,
    }


def search_records(
    store: "MemoryStore",
    query: str,
    limit: int = 10,
    tags: Optional[List[str]] = None,
    agent: Optional[str] = None,
) -> Tuple[List["ContextRecord"], int]:
    """Full-text OR search over topic/summary/details/tags (case-insensitive).

    Returns ``(results_newest_first, skipped)`` where ``skipped`` counts
    corrupted ``records.jsonl`` lines. Raises ``ValueError`` when
    ``limit`` is outside 1..100 or ``query`` is empty.
    """
    if limit is None:
        limit = 10
    if not isinstance(limit, int) or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"--limit/-n must be between 1 and {MAX_SEARCH_LIMIT} (got {limit}).")
    words = (query or "").split()
    if not words:
        raise ValueError("search requires a non-empty <query>.")
    lowered_words = [w.lower() for w in words]
    required_tags = [str(t).lower() for t in (tags or [])]
    wanted_agent = str(agent).lower() if agent else None

    records, skipped = store._load_all()
    # newest first
    records.reverse()
    hits: List[ContextRecord] = []
    for rec in records:
        if wanted_agent and rec.agent.lower() != wanted_agent:
            continue
        if required_tags:
            rec_tags = {str(t).lower() for t in (rec.tags or [])}
            if not all(rt in rec_tags for rt in required_tags):
                continue
        haystack = " ".join(
            [rec.topic or "", rec.summary or "", rec.details or "", " ".join(rec.tags or [])]
        ).lower()
        if any(w in haystack for w in lowered_words):
            hits.append(rec)
            if len(hits) >= limit:
                break
    return hits, skipped


def get_status(store: "MemoryStore") -> Dict[str, Any]:
    """Read-only workspace diagnostic (§2.2). Never creates the store."""
    workspace = str(store.workspace)
    initialized = store.bridge_dir.is_dir() and store.records_file.exists()
    if not initialized:
        return {
            "version": _package_version(),
            "workspace": workspace,
            "initialized": False,
            "records": 0,
            "store_bytes": 0,
            "last_updated": None,
            "targets": list(STATUS_TARGETS),
        }
    records, skipped = store._load_all()
    store_bytes = 0
    try:
        for child in store.bridge_dir.rglob("*"):
            if child.is_file():
                try:
                    store_bytes += child.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    latest: Optional[datetime] = None
    for rec in records:
        dt = _parse_timestamp(rec.timestamp)
        if dt and (latest is None or dt > latest):
            latest = dt
    if latest is None and records:
        try:
            mtime = datetime.fromtimestamp(store.records_file.stat().st_mtime, tz=timezone.utc)
            latest = mtime
        except OSError:
            latest = None
    payload: Dict[str, Any] = {
        "version": _package_version(),
        "workspace": workspace,
        "initialized": True,
        "records": len(records),
        "store_bytes": store_bytes,
        "last_updated": _to_zulu(latest) if latest else None,
        "targets": list(STATUS_TARGETS),
    }
    if skipped:
        payload["skipped"] = skipped
    return payload


def prune_records(
    store: "MemoryStore",
    older_than: Optional[int] = None,
    keep_last: Optional[int] = None,
    tags: Optional[List[str]] = None,
    dry_run: bool = True,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Select (and unless ``dry_run``, delete) records.

    Exactly one of ``older_than`` (>=1) / ``keep_last`` (>=0) is required.
    ``tags`` restricts deletion to records bearing ALL the tags
    (case-insensitive). Returns ``{pruned, kept, dry_run, ids}`` (+ ``skipped``
    when corrupted lines were ignored). Regenerates ``SHARED_CONTEXT.md``
    after a real deletion.
    """
    if (older_than is None) == (keep_last is None):
        raise ValueError("exactly one of --older-than / --keep-last is required.")
    if older_than is not None and (not isinstance(older_than, int) or older_than < 1):
        raise ValueError(f"--older-than must be >= 1 (got {older_than}).")
    if keep_last is not None and (not isinstance(keep_last, int) or keep_last < 0):
        raise ValueError(f"--keep-last must be >= 0 (got {keep_last}).")
    if not store.records_file.exists():
        raise FileNotFoundError(f"ACB not initialized in {store.workspace} (run 'acb init').")

    required_tags = [str(t).lower() for t in (tags or [])]

    def _tag_ok(rec: "ContextRecord") -> bool:
        if not required_tags:
            return True
        rec_tags = {str(t).lower() for t in (rec.tags or [])}
        return all(rt in rec_tags for rt in required_tags)

    oldest, skipped = store._load_all()
    n = len(oldest)
    prune_idx = set()

    if older_than is not None:
        ref = now or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        cutoff = ref - timedelta(days=older_than)
        for i, rec in enumerate(oldest):
            if not _tag_ok(rec):
                continue
            dt = _parse_timestamp(rec.timestamp)
            if dt is None:
                continue  # unparsable timestamp: keep by default
            if dt < cutoff:
                prune_idx.add(i)
    else:
        assert keep_last is not None
        # newest-first rank: first ``keep_last`` are kept unconditionally.
        newest_order = sorted(range(n), key=lambda i: (
            _parse_timestamp(oldest[i].timestamp) or datetime.min.replace(tzinfo=timezone.utc),
            i,
        ), reverse=True)
        keep = set(newest_order[: max(0, keep_last)])
        for i in range(n):
            if i in keep:
                continue
            if _tag_ok(oldest[i]):
                prune_idx.add(i)

    pruned_recs = [oldest[i] for i in sorted(prune_idx)]
    ids = [record_id(r) for r in pruned_recs]
    kept = n - len(prune_idx)

    if not dry_run and prune_idx:
        kept_recs = [rec for i, rec in enumerate(oldest) if i not in prune_idx]
        lines = [json.dumps(asdict(rec), ensure_ascii=False) + "\n" for rec in kept_recs]
        atomic_write(store.records_file, "".join(lines))
        _secure_chmod(store.records_file, 0o600)
        store.sync_markdown()

    result: Dict[str, Any] = {
        "pruned": len(prune_idx),
        "kept": kept,
        "dry_run": bool(dry_run),
        "ids": ids,
    }
    if skipped:
        result["skipped"] = skipped
    return result


@dataclass
class ContextRecord:
    """A discrete unit of shared context generated by an agent."""
    agent: str
    topic: str
    summary: str
    details: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    estimated_tokens: int = 0

    def __post_init__(self):
        _validate_record_fields(self.agent, self.topic, self.summary, self.details, self.tags)
        self.agent = sanitize_agent_name(self.agent)
        total_text = f"{self.summary}\n{self.details or ''}"
        if not self.estimated_tokens:
            self.estimated_tokens = estimate_tokens(total_text)

    def to_markdown(self) -> str:
        """Serialize record into clean, human-readable markdown format."""
        header = f"### [{self.timestamp}] {self.agent.upper()}: {self.topic}"
        body = [header, f"**Summary:** {self.summary}"]
        if self.tags:
            body.append(f"**Tags:** `{', '.join(self.tags)}`")
        if self.details:
            body.append(f"\n{self.details.strip()}")
        return "\n".join(body)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextRecord":
        return cls(
            agent=data.get("agent", "unknown"),
            topic=data.get("topic", "general"),
            summary=data.get("summary", ""),
            details=data.get("details"),
            tags=data.get("tags", []),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            estimated_tokens=data.get("estimated_tokens", 0),
        )


@dataclass
class BridgeSnapshot:
    """A full frozen snapshot of current multi-agent context."""
    version: str
    project_root: str
    records: List[ContextRecord] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def total_tokens(self) -> int:
        return sum(r.estimated_tokens for r in self.records)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "project_root": self.project_root,
            "generated_at": self.generated_at,
            "total_tokens": self.total_tokens,
            "records": [asdict(r) for r in self.records],
        }


class MemoryStore:
    """Local, offline file-backed context store for agents."""

    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace = Path(workspace_path or Path.cwd()).resolve()
        self.bridge_dir = self.workspace / ".agent_bridge"
        self.records_file = self.bridge_dir / "records.jsonl"
        self.summary_md = self.bridge_dir / "SHARED_CONTEXT.md"

    def initialize(self) -> Path:
        """Create directory structure and initialize files if missing."""
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        _secure_chmod(self.bridge_dir, 0o700)
        if not self.records_file.exists():
            atomic_write(self.records_file, "")
        _secure_chmod(self.records_file, 0o600)
        if not self.summary_md.exists():
            header = (
                "# 🧠 Shared Agent Context\n"
                "> Managed automatically by `agent-context-bridge`.\n"
                "> Shared across Hermes, Claude Code, OpenCode, and Codex.\n\n"
            )
            atomic_write(self.summary_md, header)
        _secure_chmod(self.summary_md, 0o600)
        return self.bridge_dir

    def add_record(self, record: ContextRecord) -> None:
        """Append a context record and regenerate markdown summary."""
        self.initialize()
        # Append to records JSONL
        with open(self.records_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        _secure_chmod(self.records_file, 0o600)
        self.sync_markdown()

    def _load_all(self) -> Tuple[List[ContextRecord], int]:
        """Load all records oldest-first; return ``(records, skipped)``.

        Corrupted lines (invalid JSON or failing validation) are ignored and
        counted in ``skipped`` (§6).
        """
        if not self.records_file.exists():
            return [], 0
        records: List[ContextRecord] = []
        skipped = 0
        with open(self.records_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(ContextRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, ValueError):
                    skipped += 1
                    continue
        return records, skipped

    def list_records(self, limit: Optional[int] = None) -> List[ContextRecord]:
        """Read all stored records, newest first.

        A limit of None means no limit. Non-positive limits return [].
        Positive limits are capped at MAX_LIST_LIMIT (1000).
        """
        records, _skipped = self._load_all()
        records.reverse()
        if limit is None:
            return records
        if limit <= 0:
            return []
        return records[:min(limit, MAX_LIST_LIMIT)]

    def sync_markdown(self) -> Path:
        """Compile stored records into clean SHARED_CONTEXT.md."""
        records = self.list_records()
        parts = [
            "# 🧠 Shared Agent Context",
            "> Auto-generated by `agent-context-bridge` — Offline multi-agent memory.\n",
        ]
        if not records:
            parts.append("_No shared records recorded yet._")
        else:
            for r in records:
                parts.append(r.to_markdown())
                parts.append("\n---\n")

        atomic_write(self.summary_md, "\n".join(parts))
        _secure_chmod(self.summary_md, 0o600)
        return self.summary_md

    def snapshot(self) -> BridgeSnapshot:
        """Create an exportable snapshot object."""
        records = self.list_records()
        return BridgeSnapshot(
            version=_package_version(),
            project_root=str(self.workspace),
            records=records,
        )
