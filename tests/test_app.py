from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_request_id_is_generated(client: TestClient) -> None:
    assert client.get("/health").headers["X-Request-ID"]


def test_valid_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_malformed_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert response.headers["X-Request-ID"] != "<script>alert(1)</script>"


def test_unknown_route_uses_standard_error_format(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_wrong_method_uses_standard_error_format(client: TestClient) -> None:
    response = client.delete("/patients")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
