"""The R105 evidence file names the run, the incident and the event sequence (its redaction is tests/plan_b/
test_evidence.py's job, which scans reports/skeleton/ too). The file is committed, so it must exist in CI even
though CI never runs the live suite."""

from pathlib import Path


def test_skeleton_evidence_names_run_incident_and_events():
    """The committed evidence carries run_id, incident_id and the event sequence."""
    files = sorted(Path("reports/skeleton").glob("*.txt"))
    assert files, "the committed R105 evidence is missing"  # not vacuous: the file is tracked
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "run_id=" in text and "incident_id=" in text and "events=run.accepted," in text, path
