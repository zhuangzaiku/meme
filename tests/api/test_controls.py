import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_server_starts_in_paper_mode(client: TestClient) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "paper"


def test_auto_mode_requires_validation_gate(client: TestClient) -> None:
    response = client.post("/execution-mode", json={"mode": "auto"})
    assert response.status_code == 409


def test_pause_blocks_new_orders(client: TestClient) -> None:
    client.post("/pause")
    response = client.post("/orders", json={"token": "0x1", "side": "buy"})
    assert response.status_code == 423
