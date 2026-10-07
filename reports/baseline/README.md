# Reference baseline on the owner's machine (T01)

- Date: 2026-10-07 (environment captured 2026-10-07T22:48:48Z)
- Venv: `%LOCALAPPDATA%\ops-ref-venv` (outside the repository; installed without `-e`; in-tree `build/` and `egg-info` deleted)
- Command: `python -m pytest -q` from the repository root
- Captures normalized: stdout decoded as UTF-8 (PYTHONUTF8=1) and CR stripped (tr -d '\r'); content otherwise unaltered.
- Result: the last line of `pytest-output.txt`: `58 passed, 1 warning in 4.65s`

Rule applied: any failing test is recorded verbatim here and in `pytest-output.txt`. No reference file was edited to make a test pass (R001). Failures, if any:

- none. Observation (not a failure): one third-party DeprecationWarning from `starlette/testclient.py` (anyio.abc.BlockingPortal alias deprecated), part of the baseline.
