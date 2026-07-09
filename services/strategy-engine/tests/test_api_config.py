"""GET/PUT /strategies/{id}/config: per-user parameter overrides."""

from __future__ import annotations

from fastapi.testclient import TestClient

USER = "11111111-1111-1111-1111-111111111111"
OTHER_USER = "22222222-2222-2222-2222-222222222222"


def test_put_and_get_config_roundtrip(client: TestClient) -> None:
    response = client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 5}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["overrides"] == {"fast_period": 5}
    assert body["user_id"] == USER
    assert body["is_active"] is True

    fetched = client.get(
        "/strategies/sma_crossover/config", params={"user_id": USER}
    )
    assert fetched.status_code == 200
    assert fetched.json()["overrides"] == {"fast_period": 5}


def test_put_config_updates_existing(client: TestClient) -> None:
    client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 5}},
    )
    response = client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 7, "slow_period": 40}},
    )
    assert response.status_code == 200
    assert response.json()["overrides"] == {"fast_period": 7, "slow_period": 40}


def test_configs_are_per_user(client: TestClient) -> None:
    client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 5}},
    )
    assert (
        client.get(
            "/strategies/sma_crossover/config", params={"user_id": OTHER_USER}
        ).status_code
        == 404
    )


def test_get_config_missing_404(client: TestClient) -> None:
    response = client.get(
        "/strategies/sma_crossover/config", params={"user_id": USER}
    )
    assert response.status_code == 404


def test_put_config_rejects_out_of_range(client: TestClient) -> None:
    response = client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 0}},
    )
    assert response.status_code == 422
    assert any(">= 2" in err for err in response.json()["detail"])


def test_put_config_rejects_unknown_param(client: TestClient) -> None:
    response = client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"bogus": 1}},
    )
    assert response.status_code == 422


def test_put_config_rejects_cross_field_violation(client: TestClient) -> None:
    # fast_period=50 is individually valid but breaks fast < slow(default 30)
    response = client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 50}},
    )
    assert response.status_code == 422


def test_config_unknown_strategy_404(client: TestClient) -> None:
    assert (
        client.put(
            "/strategies/nope/config", json={"user_id": USER, "overrides": {}}
        ).status_code
        == 404
    )
