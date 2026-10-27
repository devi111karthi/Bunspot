"""
Unit tests.

These exercise small pieces of behaviour in isolation: password hashing,
session key handling in logout(), and the cart-parsing/total-calculation
logic inside food_order(). The database is mocked (MagicMock) rather than
real, so these tests are fast and only fail if the *logic* is wrong.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import check_password_hash, generate_password_hash


# ── password hashing (used directly by register/login) ────────────────────
class TestPasswordHashing:
    def test_generated_hash_verifies_against_original_password(self):
        hashed = generate_password_hash("mySecret1")
        assert check_password_hash(hashed, "mySecret1") is True

    def test_generated_hash_rejects_wrong_password(self):
        hashed = generate_password_hash("mySecret1")
        assert check_password_hash(hashed, "wrongPassword") is False

    def test_hash_is_not_the_plaintext_password(self):
        hashed = generate_password_hash("mySecret1")
        assert hashed != "mySecret1"


# ── get_db() ────────────────────────────────────────────────────────────
class TestGetDb:
    def test_get_db_connects_to_configured_path_with_row_factory(self, app_module):
        import sqlite3
        conn = app_module.get_db()
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()


# ── logout() session handling ──────────────────────────────────────────
class TestLogoutSessionHandling:
    def test_logout_default_clears_only_customer_keys(self, app_module):
        with app_module.app.test_request_context("/logout"):
            from flask import session
            session["customer_id"] = 1
            session["customer_name"] = "X"
            session["customer_role"] = "customer"
            session["shop_id"] = 99
            app_module.logout()
            assert "customer_id" not in session
            assert "customer_name" not in session
            assert "customer_role" not in session
            # unrelated (shop) session data must be untouched
            assert session.get("shop_id") == 99

    def test_logout_role_shop_clears_only_shop_keys(self, app_module):
        with app_module.app.test_request_context("/logout?role=shop"):
            from flask import session
            session["shop_id"] = 1
            session["shop_name"] = "Owner"
            session["shop_role"] = "owner"
            session["customer_id"] = 5
            app_module.logout()
            assert "shop_id" not in session
            assert "shop_name" not in session
            assert "shop_role" not in session
            assert session.get("customer_id") == 5

    def test_logout_missing_keys_does_not_raise(self, app_module):
        # No session data set at all -- session.pop(..., None) must not KeyError.
        with app_module.app.test_request_context("/logout"):
            app_module.logout()  # should simply not raise


# ── food_order() cart parsing / total calculation, with a mocked DB ──────
class TestFoodOrderCartLogic:
    def _run_food_order_post(self, app_module, cart_dict_or_raw):
        """
        Helper: POST to food_order() with a mocked get_db so we only
        exercise the cart-parsing/total math, not real persistence.
        """
        raw_cart = cart_dict_or_raw if isinstance(cart_dict_or_raw, str) else json.dumps(cart_dict_or_raw)
        fake_db = MagicMock()
        fake_db.execute.return_value.fetchall.return_value = []
        # last_insert_rowid() lookups
        fake_db.execute.return_value.fetchone.return_value = [1]

        with patch.object(app_module, "get_db", return_value=fake_db):
            with app_module.app.test_request_context(
                "/food-order", method="POST", data={"cart_data": raw_cart}
            ):
                from flask import session
                session["customer_id"] = 1
                response = app_module.food_order()
                # Copy out of the session proxy before the request context
                # (and thus the proxy's backing object) goes away.
                session_snapshot = dict(session)
                return response, session_snapshot, fake_db

    def test_valid_cart_computes_correct_total(self, app_module):
        cart = {
            "1": {"qty": 2, "price": 100, "name": "Veg Burger"},
            "2": {"qty": 1, "price": 250, "name": "Cheese Pizza"},
        }
        _, session, fake_db = self._run_food_order_post(app_module, cart)
        assert session["payment_total"] == 450  # 2*100 + 1*250
        assert fake_db.commit.called

    def test_valid_cart_builds_order_items_with_subtotals(self, app_module):
        cart = {"1": {"qty": 3, "price": 50, "name": "Fries"}}
        _, session, _ = self._run_food_order_post(app_module, cart)
        assert session["payment_order_items"] == [{"name": "Fries", "qty": 3, "subtotal": 150}]

    def test_empty_cart_results_in_zero_total(self, app_module):
        _, session, _ = self._run_food_order_post(app_module, {})
        assert session["payment_total"] == 0
        assert session["payment_order_items"] == []

    def test_malformed_json_cart_data_falls_back_to_empty_cart(self, app_module):
        # 'cart_data' is not valid JSON -> the bare except should swallow it
        _, session, _ = self._run_food_order_post(app_module, "{not valid json")
        assert session["payment_total"] == 0
        assert session["payment_order_items"] == []

    def test_food_order_redirects_unauthenticated_user_to_login(self, app_module):
        with app_module.app.test_request_context("/food-order"):
            response = app_module.food_order()
            assert response.status_code == 302
            assert "/login" in response.headers["Location"]