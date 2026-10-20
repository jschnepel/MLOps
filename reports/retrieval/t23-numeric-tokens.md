# T23 numeric-token measurement

Measured 2026-10-20T00:19:02Z (lifecycle rules at 2026-10-16T12:00:00Z, T17's labelling instant) on corpus `corpus-1` (lock `81f50c2b8623`) with the 12 queries in `evals/retrieval/numeric-queries.jsonl`: each numeric query beside a control that spells the number out or drops it, through `app.search_procedures_scoped` as `mcp_read`, k = 5, in both modes. Development data only; no holdout case was read. Written by `tests/e2e/test_numeric_tokens_live.py`. The lexical query is the OR of the query's own english lexemes, after every character outside a-z and 0-9 becomes a space, so a decimal such as 0.10 reaches the search as two words.

| Mode | numeric queries hit@5 | controls hit@5 | decimal queries hit@5 | decimal controls hit@5 | pairs lost | pairs gained | forbidden rows |
|---|---|---|---|---|---|---|---|
| lexical | 5/6 = 0.83 (Wilson 95% 0.44-0.97) | 6/6 = 1.00 (Wilson 95% 0.61-1.00) | 2/3 = 0.67 (Wilson 95% 0.21-0.94) | 3/3 = 1.00 (Wilson 95% 0.44-1.00) | P06 | none | 0 |
| vector_exact | 6/6 = 1.00 (Wilson 95% 0.61-1.00) | 6/6 = 1.00 (Wilson 95% 0.61-1.00) | 3/3 = 1.00 (Wilson 95% 0.44-1.00) | 3/3 = 1.00 (Wilson 95% 0.44-1.00) | none | none | 0 |

| Pair | Numeric query (words) | Control | lexical: numeric / control | vector: numeric / control |
|---|---|---|---|---|
| P01 | Was the 0.10 offset limit for pump B22 withdrawn? (`was the 0 10 offset limit for pump b22 withdrawn`) | Was the old offset limit for pump B22 withdrawn? | 2 / 2 | 1 / 1 |
| P02 | Is 0.05 the offset band for pump B22? (`is 0 05 the offset band for pump b22`) | Is five hundredths of a millimetre the offset band for pump B22? | 2 / 1 | 1 / 1 |
| P03 | What angularity per 100 mm is allowed on pump B22? (`what angularity per 100 mm is allowed on pump b22`) | What angularity per hundred millimetres is allowed on pump B22? | 2 / 1 | 1 / 1 |
| P04 | Does the 30-day seal interval still apply to pump A17? (`does the 30 day seal interval still apply to pump a17`) | Does the monthly seal interval still apply to pump A17? | 2 / 2 | 1 / 1 |
| P05 | Is the A17 seal inspected every 14 days? (`is the a17 seal inspected every 14 days`) | Is the A17 seal inspected every fourteen days? | 1 / 1 | 1 / 1 |
| P06 | B22 offset 0.05 mm or 0.10 mm? (`b22 offset 0 05 mm or 0 10 mm`) | B22 offset five or ten hundredths of a millimetre? | miss / 1 | 1 / 1 |

## Finding

The loss is not total in lexical mode (1 of 3 decimal pairs lost (lost: P06; decimal pairs: P01, P02, P06); 1 of 6 pairs in all), so the search stays as it is (BS:71; Plan O ruling 7).

P06 is confounded: its numeric query writes `mm`, which corpus-1 never uses (its sections say millimetres), while its control writes `millimetre`, so the miss cannot be put down to the decimal split alone. An unconfounded decimal pair is a debt for the next retrieval change.

Positions are 1-based within the top 5; `miss` means not there.
