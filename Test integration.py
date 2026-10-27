"""
Integration tests.

These hit real Flask routes through the test client, backed by a real
(temporary) SQLite database. They check that a route and the DB layer work
together correctly: rows actually get inserted/updated, sessions are set
from DB data, joins return the right shape, etc. Each test focuses on one
route/feature rather than a full multi-step user journey (that's what the
functional tests are for).
"""
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from conftest import login, register_payload


# ── register ───────────────────────────────────────────────────────────
class TestRegisterIntegration:
    def test_register_inserts_customer_row_with_hashed_password(self, client, app_module):
        payload = register_payload(email="alice@example.com", password="plaintext123")
        resp = client.post("/register", data=payload, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")

        db = app_module.get_db()
        row = db.execute("SELECT * FROM users WHERE email=?", ("alice@example.com",)).fetchone()
        db.close()
        assert row is not None
        assert row["role"] == "customer"
        assert row["password"] != "plaintext123"  # must be hashed

    def test_register_duplicate_email_does_not_create_second_row(self, client, app_module):
        payload = register_payload(email="dupe@example.com")
        client.post("/register", data=payload)
        client.post("/register", data=payload)  # second attempt, same email

        db = app_module.get_db()
        count = db.execute("SELECT COUNT(*) FROM users WHERE email=?", ("dupe@example.com",)).fetchone()[0]
        db.close()
        assert count == 1

    def test_register_missing_required_field_returns_400(self, client):
        payload = register_payload()
        del payload["address"]  # address is mandatory per app.py comment
        resp = client.post("/register", data=payload)
        assert resp.status_code == 400  # Flask raises 400 on missing form key


# ── login ──────────────────────────────────────────────────────────────
class TestLoginIntegration:
    def test_customer_login_sets_customer_session_and_redirects_to_dashboard(self, client, customer):
        resp = login(client, customer["email"], customer["password"])
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/dashboard")
        with client.session_transaction() as sess:
            assert sess["customer_id"] == customer["id"]
            assert sess["customer_role"] == "customer"

    def test_owner_login_with_owner_email_sets_shop_session(self, client, owner):
        resp = login(client, owner["email"], owner["password"])
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/shop")
        with client.session_transaction() as sess:
            assert sess["shop_id"] == owner["id"]
            assert sess["shop_role"] == "owner"

    def test_login_wrong_password_does_not_set_session(self, client, customer):
        resp = login(client, customer["email"], "totally-wrong-password")
        assert resp.status_code == 200  # re-renders login page, no redirect
        with client.session_transaction() as sess:
            assert "customer_id" not in sess

    def test_login_unknown_email_does_not_set_session(self, client):
        resp = login(client, "nobody@example.com", "whatever")
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert "customer_id" not in sess
            assert "shop_id" not in sess

    def test_owner_role_user_with_non_owner_email_is_rejected(self, client, app_module):
        # Edge case: role='owner' but not logging in with the special email.
        db = app_module.get_db()
        db.execute(
            "INSERT INTO users (name,email,password,phone,address,role) VALUES (?,?,?,?,?,?)",
            ("Imposter", "notowner@example.com", generate_password_hash("pw"), "1", "addr", "owner"),
        )
        db.commit()
        db.close()
        resp = login(client, "notowner@example.com", "pw")
        assert resp.status_code == 200  # falls through to "Invalid email or password"
        with client.session_transaction() as sess:
            assert "shop_id" not in sess


# ── profile update ────────────────────────────────────────────────────
class TestProfileIntegration:
    def test_profile_post_updates_db_and_session_name(self, client, app_module, customer):
        login(client, customer["email"], customer["password"])
        resp = client.post(
            "/profile",
            data={"name": "Updated Name", "phone": "1112223333", "address": "New Address"},
        )
        assert resp.status_code == 200

        db = app_module.get_db()
        row = db.execute("SELECT * FROM users WHERE id=?", (customer["id"],)).fetchone()
        db.close()
        assert row["name"] == "Updated Name"
        assert row["phone"] == "1112223333"
        with client.session_transaction() as sess:
            assert sess["customer_name"] == "Updated Name"

    def test_profile_requires_login(self, client):
        resp = client.get("/profile", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ── table booking ─────────────────────────────────────────────────────
class TestTableBookingIntegration:
    def test_booking_post_creates_row_owned_by_customer(self, client, app_module, customer):
        login(client, customer["email"], customer["password"])
        resp = client.post(
            "/table-booking",
            data={"booking_date": "2026-09-20", "booking_time": "19:00", "guests": "4", "note": "window seat"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/my-bookings")

        db = app_module.get_db()
        row = db.execute("SELECT * FROM bookings WHERE user_id=?", (customer["id"],)).fetchone()
        db.close()
        assert row is not None
        assert row["guests"] == 4
        assert row["status"] == "pending"


# ── shop inventory management ─────────────────────────────────────────
class TestShopInventoryIntegration:
    def test_add_menu_item(self, client, app_module, owner):
        login(client, owner["email"], owner["password"])
        client.post(
            "/shop/inventory",
            data={"action": "add", "name": "Choco Bun", "price": "80", "category": "Buns", "available": "on"},
        )
        db = app_module.get_db()
        row = db.execute("SELECT * FROM menu WHERE name=?", ("Choco Bun",)).fetchone()
        db.close()
        assert row is not None
        assert row["available"] == 1
        assert row["price"] == "80" or float(row["price"]) == 80  # stored as TEXT param, sqlite is flexible

    def test_toggle_menu_item_availability(self, client, app_module, owner, seed_menu):
        login(client, owner["email"], owner["password"])
        db = app_module.get_db()
        item = db.execute("SELECT id, available FROM menu WHERE name='Veg Burger'").fetchone()
        db.close()
        assert item["available"] == 1

        client.post("/shop/inventory", data={"action": "toggle", "item_id": str(item["id"])})

        db = app_module.get_db()
        updated = db.execute("SELECT available FROM menu WHERE id=?", (item["id"],)).fetchone()
        db.close()
        assert updated["available"] == 0

    def test_delete_menu_item(self, client, app_module, owner, seed_menu):
        login(client, owner["email"], owner["password"])
        db = app_module.get_db()
        item = db.execute("SELECT id FROM menu WHERE name='Veg Burger'").fetchone()
        db.close()

        client.post("/shop/inventory", data={"action": "delete", "item_id": str(item["id"])})

        db = app_module.get_db()
        row = db.execute("SELECT * FROM menu WHERE id=?", (item["id"],)).fetchone()
        db.close()
        assert row is None

    def test_inventory_requires_shop_session(self, client):
        resp = client.get("/shop/inventory", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ── shop order status updates (join query) ─────────────────────────────
class TestShopOrdersIntegration:
    def test_updating_order_status_persists_and_joins_customer_info(self, client, app_module, owner, customer):
        db = app_module.get_db()
        cur = db.execute(
            "INSERT INTO orders (user_id,item_name,quantity,price,status) VALUES (?,?,?,?,?)",
            (customer["id"], "Veg Burger", 2, 240, "pending"),
        )
        db.commit()
        order_id = cur.lastrowid
        db.close()

        login(client, owner["email"], owner["password"])
        client.post("/shop/orders", data={"status": "confirmed", "order_id": str(order_id)})

        db = app_module.get_db()
        row = db.execute(
            """SELECT o.*, u.name as customer_name FROM orders o
               LEFT JOIN users u ON o.user_id = u.id WHERE o.id=?""",
            (order_id,),
        ).fetchone()
        db.close()
        assert row["status"] == "confirmed"
        assert row["customer_name"] == customer["name"]