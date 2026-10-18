# reference (delivered OPS-BUILD-1.0 implementation, unchanged)

This is the original single-process reference, moved here byte-for-byte in task T42. It is not a uv workspace member and is excluded from root lint, type-check and tests. It runs from its own external venv:

    uv venv "$LOCALAPPDATA/ops-ref-venv" --python 3.13
    uv pip install --python "$LOCALAPPDATA/ops-ref-venv" "./reference[web,test]"
    cd reference && "$LOCALAPPDATA/ops-ref-venv/Scripts/python" -m pytest -q

Integrity: `python -I scripts/verify_handoff.py --reference-code --manifest` (hash remap in `provenance/reference-code-hashes.remap.json`; the delivered package is `provenance/handoff-1.0.zip`). Do not port the behaviours listed in SPEC_AMENDMENTS AM-70. Traceability of its 58 tests to target tests is task T46.
