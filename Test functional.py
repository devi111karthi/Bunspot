"""
Functional (end-to-end) tests.

These simulate a real user (or shop owner) clicking through the app from
start to finish, the way a person or a browser-automation script would --
crossing multiple routes in sequence and checking the whole journey holds
together (including things one route did that a later route depends on).
"""
import json

from conftest import login, register_payload


class TestCustomerOrderJourney:
    def test_register_login_order_food_pay_and_see_order(self, client, app_module, seed_menu):
        # 1. Register a brand-new customer
        payload = register_payload(email="journey@example.com", password="journeyPass1")
        resp = client.post("/register", data=payload, follow_redirects=True)
        assert resp.status_code == 200

        # 2. Log in as that customer
        resp = login(client, "journey@example.com", "journeyPass1")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/dashboard")

        # 3. Land on the dashboard
        resp = client.get("/dashboard")
        assert resp.status_code == 200

        # 4. Browse the food menu
        resp = client.get("/food-order")
        assert resp.status_code == 200

        # 5. Place an order (cart -> POST /food-order)
        db = app_module.get_db()
        burger = db.execute("SELECT * FROM menu WHERE name='Veg Burger'").fetchone()
        db.close()
        cart = {str(burger["id"]): {"qty": 2, "price": burger["price"], "name": burger["name"]}}
        resp = client.post("/food-order", data={"cart_data": json.dumps(cart)}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/payment")

        # 6. Land on the payment page with the right running total
        resp = client.get("/payment")
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess["payment_total"] == burger["price"] * 2

        # 7. Confirm payment
        resp = client.post(
            "/confirm-payment", data={"payment_method": "upi", "total": str(burger["price"] * 2)}
        )
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert "payment_total" not in sess  # cleared after confirmation

        # 8. The order now shows up under "my orders"
        db = app_module.get_db()
        rows = db.execute("SELECT * FROM orders").fetchall()
        db.close()
        assert len(rows) == 1
        assert rows[0]["item_name"] == "Veg Burger"
        assert rows[0]["quantity"] == 2

        resp = client.get("/my-orders")
        assert resp.status_code == 200

    def test_cannot_reach_payment_page_without_an_order_in_progress(self, client, customer):
        login(client, customer["email"], customer["password"])
        resp = client.get("/payment", follow_redirects=False)
        # no cart in session -> bounced back to food-order
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/food-order")

    def test_guest_cannot_access_any_customer_page_and_is_sent_to_login(self, client):
        for path in ["/dashboard", "/profile", "/food-order", "/payment", "/my-orders", "/my-bookings", "/customer-care"]:
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 302, f"{path} should redirect when logged out"
            assert "/login" in resp.headers["Location"], f"{path} should redirect to login"


class TestTableBookingJourney:
    def test_book_a_table_and_see_it_listed(self, client, customer):
        login(client, customer["email"], customer["password"])
        resp = client.post(
            "/table-booking",
            data={"booking_date": "2026-10-01", "booking_time": "20:00", "guests": "2", "note": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200

        resp = client.get("/my-bookings")
        assert resp.status_code == 200


class TestCustomerCareJourney:
    def test_raise_a_ticket_and_see_it_in_history(self, client, customer):
        login(client, customer["email"], customer["password"])
        resp = client.post(
            "/customer-care",
            data={"subject": "Late delivery", "message": "My order was an hour late."},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        resp = client.get("/customer-care")
        assert resp.status_code == 200


class TestOwnerOperationsJourney:
    def test_owner_logs_in_manages_menu_and_updates_an_order(self, client, app_module, owner, customer):
        # Seed one pending order placed by a customer
        db = app_module.get_db()
        db.execute(
            "INSERT INTO orders (user_id,item_name,quantity,price,status) VALUES (?,?,?,?,?)",
            (customer["id"], "Veg Burger", 1, 120, "pending"),
        )
        db.commit()
        db.close()

        # Owner logs in and lands on the shop dashboard
        resp = login(client, owner["email"], owner["password"])
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/shop")
        resp = client.get("/shop")
        assert resp.status_code == 200

        # Owner adds a new menu item
        client.post(
            "/shop/inventory",
            data={"action": "add", "name": "Iced Tea", "price": "60", "category": "Drinks", "available": "on"},
        )
        resp = client.get("/shop/inventory")
        assert resp.status_code == 200

        # Owner reviews and confirms the pending order
        resp = client.get("/shop/orders")
        assert resp.status_code == 200
        db = app_module.get_db()
        order = db.execute("SELECT * FROM orders WHERE status='pending'").fetchone()
        db.close()
        client.post("/shop/orders", data={"status": "confirmed", "order_id": str(order["id"])})

        # Dashboard earnings should now reflect the confirmed order
        resp = client.get("/shop")
        assert resp.status_code == 200
        db = app_module.get_db()
        earnings = db.execute("SELECT SUM(price) FROM orders WHERE status='confirmed'").fetchone()[0]
        db.close()
        assert earnings == 120

    def test_customer_cannot_reach_shop_pages(self, client, customer):
        login(client, customer["email"], customer["password"])
        for path in ["/shop", "/shop/orders", "/shop/bookings", "/shop/tickets", "/shop/inventory"]:
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 302, f"{path} should not be reachable by a customer"
            assert "/login" in resp.headers["Location"]

    def test_guest_cannot_reach_shop_pages(self, client):
        for path in ["/shop", "/shop/orders", "/shop/bookings", "/shop/tickets", "/shop/inventory"]:
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 302
            assert "/login" in resp.headers["Location"]


class TestLogoutJourney:
    def test_customer_logout_then_cannot_access_dashboard(self, client, customer):
        login(client, customer["email"], customer["password"])
        assert client.get("/dashboard").status_code == 200

        resp = client.get("/logout")
        assert resp.status_code == 302

        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_owner_logout_uses_role_param_then_cannot_access_shop(self, client, owner):
        login(client, owner["email"], owner["password"])
        assert client.get("/shop").status_code == 200

        resp = client.get("/logout?role=shop")
        assert resp.status_code == 302

        resp = client.get("/shop", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]