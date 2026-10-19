"""`scripts/skeleton.py embed` without a database or Ollama (Plan N ruling 2; erratum 98's operator-command shape).

Catches: the command connecting as anyone but the worker; a missing pin, a model mismatch, an unreachable model or a
mixed-digest store reported as success or with a value in the message; a failure or a refusal after an earlier tenant
committed reported as "nothing written" (round 1, Minor 7: the written tenants are named, as `ingest` names them);
and the sub-command not registered.
"""

from pathlib import Path
from typing import Any

import pytest
from ops_core import embed, embeddings
from ops_core.model_pins import EmbeddingPins

from scripts import skeleton


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """No .env, the worker's settings recorded instead of a connection."""
    monkeypatch.setattr(skeleton, "load_dotenv", lambda path: {})
    monkeypatch.setattr(skeleton, "export_environment", lambda dotenv: None)
    monkeypatch.setattr(skeleton.settings, "app_postgres", lambda role: role)
    return []


def after_alpha(cause: Exception) -> embed.EmbedInterrupted:
    """A failure while writing beta, after alpha committed, as `embed.embed` raises it."""
    try:
        raise embed.EmbedInterrupted(("alpha",)) from cause
    except embed.EmbedInterrupted as error:
        return error


def test_the_command_reports_each_outcome_and_connects_as_the_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], quiet: list[Any]
) -> None:
    async def written(pg: Any, pins: EmbeddingPins) -> list[embed.Report]:
        quiet.append(pg)
        return [embed.Report("alpha", 39, 0), embed.Report("beta", 0, 30)]

    monkeypatch.setattr(skeleton, "_embed", written)
    assert skeleton.embed() == 0 and quiet == [skeleton.Role.WORKER]
    assert capsys.readouterr().out.splitlines() == ["EMBED: alpha: 39 new, 0 present", "EMBED: beta: 0 new, 30 present"]

    for failure, expected in (
        (
            embeddings.PinMismatch("the installed embedding model is not the pinned one"),
            ["EMBED: failed (UNSUPPORTED_MODE: the installed embedding model is not the pinned one), nothing written"],
        ),
        (
            embeddings.Unavailable("the embedding model could not be reached"),
            ["EMBED: failed (UNAVAILABLE: the embedding model could not be reached), nothing written"],
        ),
        (
            after_alpha(embeddings.Unavailable("the embedding model could not be reached")),
            ["EMBED: failed (UNAVAILABLE: the embedding model could not be reached) after writing alpha"],
        ),
        (
            after_alpha(embeddings.PinMismatch("the installed embedding model is not the pinned one")),
            [
                (
                    "EMBED: failed (UNSUPPORTED_MODE: the installed embedding model is not the pinned one)"
                    " after writing alpha"
                )
            ],
        ),
        (
            embed.EmbedRefused(["beta: 3 stored embeddings were made with another model digest than the pin"]),
            [
                "EMBED: refused, nothing written",
                "  beta: 3 stored embeddings were made with another model digest than the pin",
            ],
        ),
        (
            embed.EmbedRefused(["beta: another model digest appeared while embedding"], ("alpha",)),
            ["EMBED: refused after writing alpha", "  beta: another model digest appeared while embedding"],
        ),
    ):

        async def failing(pg: Any, pins: EmbeddingPins, failure: Exception = failure) -> list[embed.Report]:
            raise failure

        monkeypatch.setattr(skeleton, "_embed", failing)
        assert skeleton.embed() == 1
        assert capsys.readouterr().out.splitlines() == expected  # the problem lines too, each indented
    assert skeleton.main(["skeleton.py", "embed"]) == 1  # registered (the last failure still answers)


def test_a_missing_pin_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, quiet: list[Any]
) -> None:
    monkeypatch.setattr(embeddings, "PINS", tmp_path / "embedding-pins.json")

    async def never(pg: Any, pins: EmbeddingPins) -> list[embed.Report]:
        raise AssertionError("nothing may be embedded without a pin")

    monkeypatch.setattr(skeleton, "_embed", never)
    assert skeleton.embed() == 1
    assert capsys.readouterr().out.splitlines() == [
        "EMBED: refused, nothing written (data/embedding-pins.json is missing or malformed)"
    ]


@pytest.mark.parametrize("how", ["not-utf8", "refused"])
def test_an_unreadable_pin_is_refused_in_the_one_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    quiet: list[Any],
    how: str,
) -> None:
    """Plan N final review, m2: a pin file that cannot be decoded or read is refused as a missing one, not a traceback."""
    pins = tmp_path / "embedding-pins.json"
    pins.write_bytes(b'{"model": "' + bytes([0xFF, 0xFE]) + b'"}')
    monkeypatch.setattr(embeddings, "PINS", pins)
    if how == "refused":

        def refuse(self: Path, *args: object, **kwargs: object) -> str:
            raise PermissionError("access denied")

        monkeypatch.setattr(Path, "read_text", refuse)

    async def never(pg: Any, pins: EmbeddingPins) -> list[embed.Report]:
        raise AssertionError("nothing may be embedded without a readable pin")

    monkeypatch.setattr(skeleton, "_embed", never)
    assert skeleton.embed() == 1
    assert capsys.readouterr().out.splitlines() == [
        "EMBED: refused, nothing written (data/embedding-pins.json is missing or malformed)"
    ]
