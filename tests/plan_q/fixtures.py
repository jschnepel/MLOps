"""Tool results of the two asset reads, as mcp-read returns them (T20): the graph's retrieval reads the run's asset
status and alerts before the procedure search (Plan Q ruling 3). Every instant is the same database instant, so
the evidence is fresh by the code rule (`ops_worker.evidence`) beside `tests/plan_h/test_worker_units.SEARCH`.
"""

AT = "2026-10-08T12:00:00Z"
STATUS = {
    "tool_name": "get_asset_status",
    "status": "ok",
    "observed_at": AT,
    "truncated": False,
    "data": {"asset_id": "A17", "state": "warning", "revision": 3, "observed_at": AT, "data_source": "synthetic"},
    "error": None,
}
ALERTS = {
    "tool_name": "get_recent_alerts",
    "status": "ok",
    "observed_at": AT,
    "truncated": False,
    "data": {
        "asset_id": "A17",
        "start_at": "2026-10-07T12:00:00Z",
        "end_at": AT,
        "alerts": [
            {
                "alert_id": "6d2f3c1e-1b7a-4f55-9d6e-0a7b8c9d0e1f",
                "asset_id": "A17",
                "occurred_at": "2026-10-08T09:00:00Z",
                "code": "TEMP_HIGH",
                "message": "Bearing temperature above the warning threshold.",
                "revision": 1,
            }
        ],
        "next_cursor": None,
    },
    "error": None,
}
