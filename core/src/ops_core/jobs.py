"""Job types, their tools, run states, creators and dedup keys (AM-15 table, AM-20.4).

A job is a wake-up; the allowed tools come from the job type (plus run and attempt state at call time), never from the
worker (R131). The dedup key makes "one job per proposal / per clarification / per recovery trigger" a database
uniqueness fact rather than a hope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from ops_core.states import RunState


class Tool(StrEnum):
    """The six MCP tools (AM-15); read tools live on mcp-read, write tools on mcp-write."""

    GET_ASSET_STATUS = "get_asset_status"
    GET_RECENT_ALERTS = "get_recent_alerts"
    SEARCH_PROCEDURES = "search_procedures"
    CREATE_INCIDENT = "create_incident"
    GET_INCIDENT_RECEIPT = "get_incident_receipt"
    ABORT_INCIDENT = "abort_incident"


class Server(StrEnum):
    """Which MCP server accepts a handle for this job type (AM-15: a handle is bound to one server)."""

    READ = "read"
    WRITE = "write"


class JobType(StrEnum):
    """The eight job types (AM-20.4); a job is a wake-up, never an authority."""

    INVESTIGATE = "investigate"
    RESUME_INPUT = "resume_input"
    EXECUTE = "execute"
    RECOVER = "recover"
    EXPIRE_PROPOSALS = "expire_proposals"
    SYNC_MEMBERSHIPS = "sync_memberships"
    SWEEP_WAKEUPS = "sweep_wakeups"
    DELIVER_OUTBOX = "deliver_outbox"


@dataclass(frozen=True)
class JobRule:
    """What a job type may do: its tools, the run states it runs in, its server, creators and dedup key shape.

    TODO(T15): AM-15 derives the allowlist from the job type *plus the run state and the attempt state* (for example
    `create_incident` only while the attempt is absent or INTENT). This rule holds the job-type dimension; T15's
    `resolve_invocation` adds the run-state and attempt-state filters at call time.
    """

    type: JobType
    allowed_tools: frozenset[Tool]
    run_states: frozenset[RunState]  # empty for maintenance jobs, which hold no run lease
    server: Server | None
    created_by: tuple[str, ...]  # AM-20.4 "Inserted by"
    dedup_pattern: str  # documentation of the key shape; `dedup_key` builds it


_READ: Final = frozenset({Tool.GET_ASSET_STATUS, Tool.GET_RECENT_ALERTS, Tool.SEARCH_PROCEDURES})
_S = RunState
JOB_RULES: Final[dict[JobType, JobRule]] = {
    JobType.INVESTIGATE: JobRule(
        JobType.INVESTIGATE,
        _READ,
        frozenset({_S.QUEUED, _S.RETRIEVING, _S.DRAFTING}),
        Server.READ,
        ("api", "create_revision"),
        "run_id:revision",
    ),
    JobType.RESUME_INPUT: JobRule(
        JobType.RESUME_INPUT,
        _READ,
        frozenset({_S.AWAITING_INPUT, _S.QUEUED}),
        Server.READ,
        ("api",),
        "run_id:clarification_event_id",
    ),
    JobType.EXECUTE: JobRule(
        JobType.EXECUTE,
        frozenset({Tool.CREATE_INCIDENT}),
        frozenset({_S.APPROVED, _S.EXECUTING}),
        Server.WRITE,
        ("record_decision",),
        "proposal_id",
    ),
    JobType.RECOVER: JobRule(
        JobType.RECOVER,
        frozenset({Tool.CREATE_INCIDENT, Tool.GET_INCIDENT_RECEIPT, Tool.ABORT_INCIDENT}),
        frozenset({_S.EXECUTING, _S.OUTCOME_UNKNOWN, _S.ESCALATED, _S.ABANDONED_UNVERIFIED}),
        Server.WRITE,
        ("mark_unknown", "worker", "reclaim_leases"),  # never an MCP server (AM-15)
        "action_id:trigger",
    ),
    **{
        t: JobRule(t, frozenset(), frozenset(), None, ("sweeper",), "name:minute_bucket")
        for t in (JobType.EXPIRE_PROPOSALS, JobType.SYNC_MEMBERSHIPS, JobType.SWEEP_WAKEUPS, JobType.DELIVER_OUTBOX)
    },
}

RECOVER_CADENCE: Final = (300, 3600, 48)  # every 5 min for the first hour, then hourly, 48 attempts (AM-20.4)
# Both patterns are used with `fullmatch`: `$` also matches before a trailing newline, so `match` + `$` would accept
# "timeout\n" as a second, distinct dedup key for the same trigger and defeat the uniqueness this module exists for.
_BUCKET_RE: Final = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"  # one-minute bucket, UTC, no seconds
_BUCKET: Final = re.compile(_BUCKET_RE)
# AM-20.4 recover triggers; a sweep trigger carries the same minute bucket as maintenance jobs, so one sweep tick
# cannot mint several keys for one action.
_TRIGGER: Final = re.compile(rf"timeout|cancel|deadline|sweep:{_BUCKET_RE}")
# The parts each job type's key is built from (AM-20.4). Every id is a UUID and a revision is a positive int, so two
# job types can never mint the same key: an int where a UUID belongs (a clarification event's per-run `sequence` in
# place of its `event_id`) would make `INVESTIGATE(run, revision=2)` and `RESUME_INPUT(run, 2)` both "<run>:2", and
# `INSERT … ON CONFLICT (dedup_key) DO NOTHING` would silently drop the second job.
_UUID_PARTS: Final = frozenset({"run_id", "proposal_id", "action_id", "clarification_event_id"})
_PARTS: Final = {
    JobType.INVESTIGATE: ("run_id", "revision"),
    JobType.RESUME_INPUT: ("run_id", "clarification_event_id"),
    JobType.EXECUTE: ("proposal_id",),
    JobType.RECOVER: ("action_id", "trigger"),
}


class DedupKeyError(ValueError):
    """A dedup key part is missing, unexpected, of the wrong type, or malformed (AM-20.4)."""


def server_for(job_type: JobType) -> Server | None:
    """The server whose handles this job type receives, or None for maintenance jobs that call no tool."""
    return JOB_RULES[job_type].server


def _check_part(job_type: JobType, part: str, value: object) -> None:
    if part in _UUID_PARTS:
        if not isinstance(value, UUID):
            raise DedupKeyError(f"{job_type.value} needs {part} as a UUID")
    elif part == "revision":
        # bool is an int subclass but never a revision.
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise DedupKeyError(f"{job_type.value} needs revision as an int >= 1")
    elif not isinstance(value, str) or not value:  # trigger, minute_bucket: dedup_key checks their shape
        raise DedupKeyError(f"{job_type.value} needs {part} as a non-empty str")


def dedup_key(job_type: JobType, **ids: UUID | int | str) -> str:
    """Build the AM-20.4 dedup key for a job.

    Ids (`run_id`, `proposal_id`, `action_id`, `clarification_event_id`) must be UUIDs, `revision` an int >= 1, and
    `trigger` / `minute_bucket` strings of their documented shape.

    Raises:
        DedupKeyError: a part is missing, unexpected, of the wrong type, or malformed.
    """
    needed = _PARTS.get(job_type, ("minute_bucket",))
    # A misspelt part (`proposal_ID=`) must fail loudly rather than be ignored next to a valid-looking key.
    if extra := sorted(set(ids) - set(needed)):
        raise DedupKeyError(f"unexpected key(s): {', '.join(extra)}")
    for part in needed:
        _check_part(job_type, part, ids.get(part))
    match job_type:
        case JobType.INVESTIGATE:
            return f"{ids['run_id']}:{ids['revision']}"
        case JobType.RESUME_INPUT:
            return f"{ids['run_id']}:{ids['clarification_event_id']}"
        case JobType.EXECUTE:
            return str(ids["proposal_id"])
        case JobType.RECOVER:
            trigger = str(ids["trigger"])
            if not _TRIGGER.fullmatch(trigger):
                raise DedupKeyError(
                    "recover trigger must be one of timeout, cancel, deadline, sweep:<YYYY-MM-DDTHH:MM>"
                )
            return f"{ids['action_id']}:{trigger}"
        case _:
            bucket = str(ids["minute_bucket"])
            if not _BUCKET.fullmatch(bucket):
                raise DedupKeyError("maintenance jobs need minute_bucket as YYYY-MM-DDTHH:MM")
            return f"{job_type.value}:{bucket}"
