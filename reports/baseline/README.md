# Reference baseline on the owner's machine (T01)

- Date: 2026-10-07 (environment captured 2026-10-07T22:48:48Z)
- Venv: `%LOCALAPPDATA%\ops-ref-venv` (outside the repository; installed without `-e`; in-tree `build/` and `egg-info` deleted)
- Command: `python -m pytest -q` from the repository root
- Result: the last line of `pytest-output.txt`: `58 passed, 1 warning in 7.42s`

Rule applied: any failing test is recorded verbatim here and in `pytest-output.txt`. No reference file was edited to make a test pass (R001). Failures, if any:

- none (the one warning is a starlette/anyio DeprecationWarning from `starlette/testclient.py`, third-party code)
