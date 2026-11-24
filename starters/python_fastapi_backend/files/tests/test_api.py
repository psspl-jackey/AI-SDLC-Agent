"""API tests for the starter backend. Each test run uses its own SQLite file."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    import app.db, app.models, app.auth, app.seed, app.main  # noqa: E401
    for mod in (app.db, app.models, app.auth, app.seed, app.main):
        importlib.reload(mod)
    with TestClient(app.main.app) as c:
        yield c


def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def seed_users():
    from app.seed import load_seed
    users = load_seed()["users"]
    admin = next(u for u in users if u.get("role") == "admin")
    user = next(u for u in users if u.get("role", "user") == "user")
    return admin, user


def test_health_and_seed_data(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/categories").json()
    assert client.get("/items").json()


def test_wrong_password_is_refused(client):
    _, user = seed_users()
    assert client.post("/auth/login", json={"email": user["email"], "password": "wrong"}).status_code == 401


def test_new_item_waits_for_admin_approval(client):
    admin, user = seed_users()
    headers = login(client, user["email"], user["password"])
    cat = client.get("/categories").json()[0]["id"]
    item = client.post("/items", json={"title": "Test item", "price": 100, "category_id": cat}, headers=headers).json()
    assert item["status"] == "pending"
    assert item["id"] not in [i["id"] for i in client.get("/items").json()]
    admin_headers = login(client, admin["email"], admin["password"])
    assert client.patch(f"/admin/items/{item['id']}", json={"status": "active"}, headers=admin_headers).status_code == 200
    assert item["id"] in [i["id"] for i in client.get("/items").json()]


def test_admin_routes_need_an_admin(client):
    _, user = seed_users()
    headers = login(client, user["email"], user["password"])
    assert client.get("/admin/users", headers=headers).status_code == 403
    assert client.get("/admin/users").status_code == 401


def test_favourites(client):
    _, user = seed_users()
    headers = login(client, user["email"], user["password"])
    item_id = client.get("/items").json()[0]["id"]
    client.post(f"/favourites/{item_id}", headers=headers)
    assert [i["id"] for i in client.get("/favourites", headers=headers).json()] == [item_id]


def test_dummy_payment_gives_static_responses(client):
    _, user = seed_users()
    headers = login(client, user["email"], user["password"])
    ok = client.post("/payments/dummy", json={"amount": 99, "purpose": "feature"}, headers=headers).json()
    assert ok["status"] == "success" and ok["reference"].startswith("DUMMY-")
    failed = client.post("/payments/dummy", json={"amount": 99, "simulate_failure": True}, headers=headers).json()
    assert failed["status"] == "failed"


def test_phone_is_masked_until_login_and_seller_can_mark_sold(client):
    admin, user = seed_users()
    item = client.get("/items").json()[0]
    assert "x" in item["seller"]["phone_masked"]
    assert client.get(f"/items/{item['id']}/contact").status_code == 401
    headers = login(client, user["email"], user["password"])
    assert client.get(f"/items/{item['id']}/contact", headers=headers).json()["phone"]
    mine = client.get("/my/items", headers=headers).json()
    live = next(i for i in mine if i["status"] == "active")
    assert client.patch(f"/my/items/{live['id']}", json={"status": "sold"}, headers=headers).json()["status"] == "sold"
    assert live["id"] not in [i["id"] for i in client.get("/items").json()]


def test_sorting_by_price(client):
    prices = [i["price"] for i in client.get("/items?sort=price_asc").json()]
    assert prices == sorted(prices)
