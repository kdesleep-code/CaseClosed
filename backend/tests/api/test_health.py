from __future__ import annotations


def test_health_endpoint_returns_200(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200

