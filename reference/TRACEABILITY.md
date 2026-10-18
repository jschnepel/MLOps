# Reference test traceability (T46, R123)

The delivered reference (`reference/`, hash-pinned) has 58 tests. Each is **ported** (rewritten against `core`, the target test named), **replaced** by a target test owned by a later task, or **dropped** with the AM-70 reason. Dispositions were decided on 2026-10-08 from `SPEC_AMENDMENTS.md` AM-70 and the task graph; `tests/plan_c/test_traceability.py` checks this table against the reference sources.

| Reference test | Disposition | Target test | Owning task | Reason |
|---|---|---|---|---|
| `test_control.py::test_invalid_hours[None]` | replace-by | tests/acceptance R018 missing interval routes to clarify | T12 | the target makes hours optional; a missing interval is a clarification, not a 422 (AM-16) |
| `test_control.py::test_invalid_hours[0]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[169]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[-1]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[True]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | strict mode rejects bool |
| `test_control.py::test_invalid_hours[1.5]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[24]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | the string '24' |
| `test_control.py::test_valid_hours[1]` | port | test_contracts.py::test_valid_hours | T07 | |
| `test_control.py::test_valid_hours[24]` | port | test_contracts.py::test_valid_hours | T07 | |
| `test_control.py::test_valid_hours[168]` | port | test_contracts.py::test_valid_hours | T07 | |
| `test_control.py::test_canonical_hash_order` | port | test_canonical.py::test_known_bytes_and_hash | T07 | canonical JSON v1 |
| `test_control.py::test_clarification_then_proposal` | replace-by | tests/acceptance R018 clarification round trip | T12 | admission clarification_reply route; resume in T20 |
| `test_control.py::test_stale_clarification` | replace-by | tests/acceptance R017 expected_version 409 | T12 | |
| `test_control.py::test_success` | replace-by | tests/acceptance R105 walking skeleton e2e | T08 | record_outcome in T22 |
| `test_control.py::test_no_write_without_approval` | replace-by | tests/acceptance R045 grant gate | T21 | |
| `test_control.py::test_operator_cannot_approve` | replace-by | tests/acceptance R043 reviewer membership | T21 | |
| `test_control.py::test_reader_cannot_create` | replace-by | tests/acceptance R015 admission authorization | T12 | |
| `test_control.py::test_cross_team_asset_hidden` | replace-by | tests/acceptance R028 asset-sim tenant filter | T16 | admission 404 in T12 |
| `test_control.py::test_cross_team_run_denied` | replace-by | tests/acceptance R007 RLS and R115 404 mapping | T09 | |
| `test_control.py::test_cross_team_events_denied` | replace-by | tests/acceptance R053 authorized event history | T14 | |
| `test_control.py::test_self_approval_denied` | replace-by | tests/acceptance R093 independence covers every author | T21 | |
| `test_control.py::test_proposal_hash_mismatch` | replace-by | tests/acceptance R044 expected_payload_sha256 | T21 | |
| `test_control.py::test_stale_version` | replace-by | tests/acceptance R044 stale revision 409 | T21 | |
| `test_control.py::test_expired_proposal` | replace-by | tests/acceptance R092 lazy expiry to BLOCKED_REVIEW | T21 | |
| `test_control.py::test_expired_approval` | replace-by | tests/acceptance R092 expiry at grant | T21 | |
| `test_control.py::test_approver_revoked_before_execution` | replace-by | tests/acceptance R086 revocation before grant | T21 | enabled check in T11 |
| `test_control.py::test_requester_revoked_before_execution` | replace-by | tests/acceptance R086 requester revoked | T21 | |
| `test_control.py::test_changed_evidence` | replace-by | tests/acceptance R116 asset freshness at grant | T21 | |
| `test_control.py::test_mutated_proposal` | replace-by | tests/acceptance R044 hash verified at grant | T21 | immutable proposals in T09 |
| `test_control.py::test_duplicate_decision_and_execute` | replace-by | tests/acceptance R090 concurrent decide and execute | T21 | AM-70 names this test as weak; replaced by concurrent tests |
| `test_control.py::test_concurrent_destination_dedup` | replace-by | tests/acceptance R047 action_key ON CONFLICT | T10 | |
| `test_control.py::test_destination_idempotency_key_content_conflict` | replace-by | tests/acceptance R049 CONFLICT on changed hash | T10 | |
| `test_control.py::test_lost_response_restart_and_reconcile` | replace-by | tests/acceptance R048 lost response recovery | T22 | fault hook in T10 |
| `test_control.py::test_unknown_cannot_blind_retry` | replace-by | tests/acceptance R050 no blind retry after SENT | T22 | |
| `test_control.py::test_executing_without_receipt_stays_unknown` | drop | | | AM-70 stuck EXECUTING after a crash (service.py:175-178, :213-216); the surviving invariant (NOT_FOUND is never no-commit) is R050/R096 in T22 |
| `test_control.py::test_cancel_before_write` | replace-by | tests/acceptance R046 cancel wins before grant | T21 | |
| `test_control.py::test_cancel_does_not_undo_commit` | replace-by | tests/acceptance R046 cancel-response reports the grant | T22 | |
| `test_control.py::test_rejection` | replace-by | tests/acceptance R043 rejection path | T21 | |
| `test_control.py::test_duplicate_request_key` | replace-by | tests/acceptance R016 idempotency replay | T12 | |
| `test_control.py::test_request_key_scoped_by_identity` | replace-by | tests/acceptance R016 key scoped by identity | T12 | |
| `test_control.py::test_unknown_citation_rejected` | replace-by | tests/acceptance R041 citation membership | T19 | |
| `test_control.py::test_model_cannot_add_authorization_field` | replace-by | test_contracts.py::test_draft_rules | T07 | R004, already green |
| `test_control.py::test_missing_documents_abstains` | replace-by | tests/acceptance R114 evidence-sufficient rule | T20 | |
| `test_control.py::test_cancellation_during_generation_discards_output` | replace-by | tests/acceptance R098 cancel mid-draft | T20 | lease cancel in T13 |
| `test_control.py::test_event_cursor` | replace-by | tests/acceptance R089 gap-free sequence | T14 | |
| `test_control.py::test_empty_and_oversize_message` | replace-by | test_contracts.py::test_empty_and_oversize_message | T07 | already green; 422 mapping in T12 |
| `test_control.py::test_reader_cannot_reconcile` | replace-by | tests/acceptance R131 recover handles only on mcp-write | T47 | |
| `test_api.py::test_health` | replace-by | tests/acceptance health endpoints (BUILD_SPEC §7) | T12 | |
| `test_api.py::test_auth_required` | replace-by | tests/acceptance R011 401 without identity | T11 | |
| `test_api.py::test_bad_token` | replace-by | tests/acceptance R011 unknown bearer | T11 | |
| `test_api.py::test_me` | replace-by | tests/acceptance GET /api/v1/me | T11 | |
| `test_api.py::test_create_and_read` | replace-by | tests/acceptance R015 and R115 202/404 | T12 | |
| `test_api.py::test_cannot_supply_identity_or_approved_field` | replace-by | test_contracts.py::test_authority_fields_are_rejected_at_every_depth | T07 | already green; 422 mapping in T12 |
| `test_api.py::test_bool_hours_rejected` | replace-by | test_contracts.py::test_invalid_hours_rejected | T07 | already green; 422 mapping in T12 |
| `test_api.py::test_cross_origin_mutation_rejected` | replace-by | tests/acceptance R012 origin check | T11 | |
| `test_api.py::test_host_restriction` | replace-by | tests/acceptance trusted host (BUILD_SPEC §9) | T11 | |
| `test_api.py::test_complete_api_workflow` | replace-by | tests/acceptance R105 walking skeleton e2e | T08 | |
| `test_api.py::test_ui_served_with_security_headers` | drop | | | reference-only demo UI (web/); the target UI is T26 and its CSP is BUILD_SPEC §9 |
