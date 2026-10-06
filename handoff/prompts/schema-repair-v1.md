# Runtime prompt starter — schema-repair-v1

**Status:** Target template. Invoke at most once, only with remaining compute/token budget, and without new tools or permissions.

Correct the supplied draft so that it matches the reviewed output schema. Use only the same permitted evidence and exact allowed evidence IDs. Do not invent sources, approval, execution, root cause or missing observations. Preserve supported meaning and uncertainty. If the task cannot be supported, return an appropriate structured abstention. Return JSON only; no additional fields or private reasoning transcript.

Application inputs: sanitized invalid output; safe structural validation errors; original confirmed request; permitted evidence; expected schema. Never include stack traces, tokens or unauthorized source text in repair feedback. Persistent invalid output is a controlled failure, not a reason to keep retrying.
