# T20 graph on the Postgres saver — 2026-10-25T07:20:56Z

- R108: a step-N+1 node found step N's checkpoint already in the Postgres saver (durability=sync)
- R122: api, sweeper and mcp_read refused at schema `checkpoints`; worker DML; versions 0-9 recorded
- proposal path: load_run → route_request → retrieve_evidence → route_request → draft_with_langchain → route_request → validate_and_freeze → route_request → await_independent_decision; ends AWAITING_APPROVAL, lease released
- clarification across a restart: QUEUED → RETRIEVING → DRAFTING → AWAITING_INPUT → QUEUED → RETRIEVING → DRAFTING → AWAITING_APPROVAL
- answer_only: load_run → route_request → retrieve_evidence → route_request → draft_with_langchain → route_request → publish_state; ends ANSWERED, cited, no proposal
