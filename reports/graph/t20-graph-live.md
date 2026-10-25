# T20 graph on the Postgres saver — 2026-10-25T08:19:03Z

- R108: step N's values were stored when step N+1 ran, on the Postgres saver under sync durability; the async race is not shown
- R122: api, sweeper and mcp_read refused at schema `checkpoints`; worker selects from `checkpoint_writes` but not the bookkeeping table (its writes are shown by the other tests); versions 0-9 recorded
- proposal path: load_run → route_request → retrieve_evidence → route_request → draft_with_langchain → route_request → validate_and_freeze → route_request → await_independent_decision; ends AWAITING_APPROVAL, lease released
- clarification across a restart: QUEUED → RETRIEVING → DRAFTING → AWAITING_INPUT → QUEUED → RETRIEVING → DRAFTING → AWAITING_APPROVAL
- answer_only: load_run → route_request → retrieve_evidence → route_request → draft_with_langchain → route_request → publish_state; ends ANSWERED, cited, no proposal
