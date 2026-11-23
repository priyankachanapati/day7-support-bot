
import pytest

from app import app, CUSTOMERS, REFUNDS


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-for-testing-only")

    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


def login(client, email, password):
    return client.post(
        "/login",
        json={"email": email, "password": password},
    )


def get_token(client, email, password):
    response = login(client, email, password)
    assert response.status_code == 200
    return response.get_json()["access_token"]


@pytest.fixture
def demo_passwords(monkeypatch):
    from werkzeug.security import generate_password_hash

    CUSTOMERS["ravi.kumar@example.com"]["password_hash"] = (
        generate_password_hash(
            "RaviDemo@123",
            method="pbkdf2:sha256"
        )
    )

    CUSTOMERS["priya.s@example.com"]["password_hash"] = (
        generate_password_hash(
            "PriyaDemo@123",
            method="pbkdf2:sha256"
        )
    )


def test_login_success(client, demo_passwords):
    response = login(
        client, "ravi.kumar@example.com", "RaviDemo@123"
    )

    assert response.status_code == 200
    assert "access_token" in response.get_json()


def test_login_wrong_password(client, demo_passwords):
    response = login(
        client, "ravi.kumar@example.com", "wrong-password"
    )

    assert response.status_code == 401


def test_chat_requires_authentication(client):
    response = client.post(
        "/chat",
        json={"message": "Hello"},
    )

    assert response.status_code == 401


def test_chat_returns_a_reply(client, demo_passwords):
    token = get_token(
        client, "ravi.kumar@example.com", "RaviDemo@123"
    )

    response = client.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert "reply" in response.get_json()


def test_order_status(client, demo_passwords):
    token = get_token(
        client, "ravi.kumar@example.com", "RaviDemo@123"
    )

    response = client.post(
        "/chat",
        json={"message": "Where is my order 10231?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.get_json()["action_result"] == "Shipped"


def test_unknown_order(client, demo_passwords):
    token = get_token(
        client, "priya.s@example.com", "PriyaDemo@123"
    )

    response = client.post(
        "/chat",
        json={"message": "What is the status of order 99999?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.get_json()["action_result"] == "Order not found"


def test_customer_cannot_access_another_customers_order(
    client, demo_passwords
):
    token = get_token(
        client, "priya.s@example.com", "PriyaDemo@123"
    )

    response = client.post(
        "/chat",
        json={"message": "Where is my order 10231?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_account_deletion_is_blocked(client, demo_passwords):
    email = "ravi.kumar@example.com"
    token = get_token(client, email, "RaviDemo@123")

    response = client.post(
        "/chat",
        json={"message": "Please close my account."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert "disabled" in response.get_json()["action_result"].lower()
    assert email in CUSTOMERS


def test_unauthorized_refund_is_blocked(client, demo_passwords):
    REFUNDS.clear()

    token = get_token(
        client, "ravi.kumar@example.com", "RaviDemo@123"
    )

    response = client.post(
        "/chat",
        json={"message": "I want a refund for order 10231."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert "disabled" in response.get_json()["action_result"].lower()
    assert REFUNDS == []
