"""T05 DoD: the dev profile is up, healthy, and `docker compose ps` shows only 127.0.0.1 bindings."""


def test_running_services_are_healthy(compose_ps: list[dict]) -> None:
    names = {row["Service"] for row in compose_ps}
    assert "postgres" in names
    for row in compose_ps:
        assert row["State"] == "running", row
        assert row.get("Health", "") in ("healthy", ""), row


def test_every_live_binding_is_loopback(compose_ps: list[dict]) -> None:
    assert compose_ps, "no service is running"
    for row in compose_ps:
        published = [pub for pub in (row.get("Publishers") or []) if pub.get("PublishedPort")]
        assert published, (row["Service"], "no published port reported")
        for pub in published:
            assert pub.get("URL") == "127.0.0.1", (row["Service"], pub)
