# Holdout custody

Status: NOT YET SEALED — the owner performs step 9; until then the seal test is skipped and the probe refuses to run.

- Part 1 (intents) sealed on: [date] by the owner, without AI assistance.
- Case count: [n]
- External record: [email subject, date]
- The cases are NOT in this repository and must never be placed in any directory the agent can read.
- Part 2 (gold labels against the frozen corpus) is task T41 and re-seals the file.
- Any prompt tuning before this date would invalidate the seal; the probe (T02) checks that this seal file exists before it runs.
