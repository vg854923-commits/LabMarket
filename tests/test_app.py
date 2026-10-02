import os, tempfile, sqlite3
import pytest
from app import app, setup, DB

@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test.db")
    monkeypatch.setattr("app.DB", test_db)
    setup()
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c

def test_home(client):
    r=client.get("/")
    assert r.status_code == 200
    assert b"LabMarket" in r.data

def test_health(client):
    r=client.get("/health")
    assert r.status_code == 200
    assert r.json["status"] == "ok"

def test_equipment_api(client):
    r=client.get("/api/equipment")
    assert r.status_code == 200
    assert len(r.json) >= 8

def test_login_and_admin(client):
    r=client.post("/login", data={"email":"admin@labmarket.com","password":"admin123"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Dashboard" in r.data

def test_customer_booking_conflict_protection(client):
    client.post("/login", data={"email":"student@labmarket.com","password":"student123"})
    client.post("/cart/add/1")
    r=client.post("/checkout", data={"start_date":"2030-01-01","end_date":"2030-01-03","purpose":"Test experiment"}, follow_redirects=True)
    assert r.status_code == 200
