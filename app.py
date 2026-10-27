from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, json

app = Flask(__name__)
app.secret_key = 'bunspot_secret_key_2024'

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'bunspot.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    return redirect(url_for('login'))

# ── REGISTER (phone + address now mandatory) ──────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form['name']
        email    = request.form['email']
        password = generate_password_hash(request.form['password'])
        phone    = request.form['phone']
        address  = request.form['address']
        db = get_db()
        try:
            db.execute(
                'INSERT INTO users (name,email,password,phone,address,role) VALUES (?,?,?,?,?,?)',
                (name, email, password, phone, address, 'customer'))
            db.commit()
            flash('Registered! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists.', 'danger')
        finally:
            db.close()
    return render_template('register.html')

# ── LOGIN ─────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            if email == 'owner@bunspot.in' and user['role'] == 'owner':
                session['shop_id']   = user['id']
                session['shop_name'] = user['name']
                session['shop_role'] = 'owner'
                return redirect(url_for('shop_dashboard'))
            elif user['role'] == 'customer':
                session['customer_id']   = user['id']
                session['customer_name'] = user['name']
                session['customer_role'] = 'customer'
                return redirect(url_for('customer_dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('login.html')

# ── LOGOUT ────────────────────────────────────────────────────────────────────
@app.route('/logout')
def logout():
    role = request.args.get('role', 'customer')
    if role == 'shop':
        session.pop('shop_id', None); session.pop('shop_name', None); session.pop('shop_role', None)
    else:
        session.pop('customer_id', None); session.pop('customer_name', None); session.pop('customer_role', None)
    return redirect(url_for('home'))

# ── CUSTOMER DASHBOARD ────────────────────────────────────────────────────────
@app.route('/dashboard')
def customer_dashboard():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    db = get_db()
    orders   = db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC', (session['customer_id'],)).fetchall()
    bookings = db.execute('SELECT * FROM bookings WHERE user_id=? ORDER BY booking_date DESC', (session['customer_id'],)).fetchall()
    db.close()
    return render_template('customer_dashboard.html', orders=orders, bookings=bookings, page_role='customer')

# ── PROFILE ───────────────────────────────────────────────────────────────────
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        name    = request.form['name']
        phone   = request.form['phone']
        address = request.form['address']
        db.execute('UPDATE users SET name=?, phone=?, address=? WHERE id=?',
                   (name, phone, address, session['customer_id']))
        db.commit()
        session['customer_name'] = name
        flash('Profile updated successfully!', 'success')
    user = db.execute('SELECT * FROM users WHERE id=?', (session['customer_id'],)).fetchone()
    db.close()
    return render_template('profile.html', user=user, page_role='customer')

# ── FOOD ORDER ────────────────────────────────────────────────────────────────
@app.route('/food-order', methods=['GET','POST'])
def food_order():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    db = get_db()
    menu_items = db.execute('SELECT * FROM menu WHERE available=1').fetchall()
    if request.method == 'POST':
        cart_data = request.form.get('cart_data', '{}')
        try:
            cart = json.loads(cart_data)
        except:
            cart = {}
        total = 0; order_items = []; order_ids = []
        for item_id, info in cart.items():
            qty = int(info['qty']); price = float(info['price']); name = info['name']
            subtotal = price * qty; total += subtotal
            db.execute('INSERT INTO orders (user_id,item_name,quantity,price,status) VALUES (?,?,?,?,?)',
                       (session['customer_id'], name, qty, subtotal, 'pending'))
            last = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            order_ids.append(str(last))
            order_items.append({'name': name, 'qty': qty, 'subtotal': int(subtotal)})
        db.commit(); db.close()
        session['payment_order_ids']   = ','.join(order_ids)
        session['payment_order_items'] = order_items
        session['payment_total']       = int(total)
        return redirect(url_for('payment'))
    db.close()
    return render_template('food_order.html', menu_items=menu_items, page_role='customer')

# ── PAYMENT ───────────────────────────────────────────────────────────────────
@app.route('/payment')
def payment():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    order_items = session.get('payment_order_items', [])
    total       = session.get('payment_total', 0)
    order_ids   = session.get('payment_order_ids', '')
    if not order_items:
        return redirect(url_for('food_order'))
    return render_template('payment.html', order_items=order_items, total=total, order_ids=order_ids, page_role='customer')

@app.route('/confirm-payment', methods=['POST'])
def confirm_payment():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    payment_method = request.form.get('payment_method', 'cash')
    total          = request.form.get('total', 0)
    session.pop('payment_order_ids', None)
    session.pop('payment_order_items', None)
    session.pop('payment_total', None)
    return render_template('order_success.html', payment_method=payment_method, total=total, page_role='customer')

# ── MY ORDERS ─────────────────────────────────────────────────────────────────
@app.route('/my-orders')
def my_orders():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    db = get_db()
    orders = db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC', (session['customer_id'],)).fetchall()
    db.close()
    return render_template('my_orders.html', orders=orders, page_role='customer')

# ── TABLE BOOKING ─────────────────────────────────────────────────────────────
@app.route('/table-booking', methods=['GET','POST'])
def table_booking():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        db = get_db()
        db.execute('INSERT INTO bookings (user_id,booking_date,booking_time,guests,note,status) VALUES (?,?,?,?,?,?)',
                   (session['customer_id'], request.form['booking_date'], request.form['booking_time'],
                    request.form['guests'], request.form.get('note',''), 'pending'))
        db.commit(); db.close()
        flash('Table booked successfully!', 'success')
        return redirect(url_for('my_bookings'))
    return render_template('table_booking.html', page_role='customer')

@app.route('/my-bookings')
def my_bookings():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    db = get_db()
    bookings = db.execute('SELECT * FROM bookings WHERE user_id=? ORDER BY booking_date DESC', (session['customer_id'],)).fetchall()
    db.close()
    return render_template('my_bookings.html', bookings=bookings, page_role='customer')

# ── CUSTOMER CARE ─────────────────────────────────────────────────────────────
@app.route('/customer-care', methods=['GET','POST'])
def customer_care():
    if not session.get('customer_id'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        db = get_db()
        db.execute('INSERT INTO tickets (user_id,subject,message,status) VALUES (?,?,?,?)',
                   (session['customer_id'], request.form['subject'], request.form['message'], 'open'))
        db.commit(); db.close()
        flash('Your message has been sent!', 'success')
        return redirect(url_for('customer_care'))
    db = get_db()
    tickets = db.execute('SELECT * FROM tickets WHERE user_id=? ORDER BY created_at DESC', (session['customer_id'],)).fetchall()
    db.close()
    return render_template('customer_care.html', tickets=tickets, page_role='customer')

# ── SHOP DASHBOARD ────────────────────────────────────────────────────────────
@app.route('/shop')
def shop_dashboard():
    if not session.get('shop_id'):
        return redirect(url_for('login'))
    db = get_db()
    total_orders   = db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    pending_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
    total_bookings = db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]
    pending_books  = db.execute("SELECT COUNT(*) FROM bookings WHERE status='pending'").fetchone()[0]
    open_tickets   = db.execute("SELECT COUNT(*) FROM tickets WHERE status='open'").fetchone()[0]
    total_menu     = db.execute('SELECT COUNT(*) FROM menu').fetchone()[0]
    total_earnings = db.execute("SELECT SUM(price) FROM orders WHERE status='confirmed'").fetchone()[0] or 0
    db.close()
    return render_template('shop_dashboard.html',
        total_orders=total_orders, pending_orders=pending_orders,
        total_bookings=total_bookings, pending_books=pending_books,
        open_tickets=open_tickets, total_menu=total_menu,
        total_earnings=int(total_earnings), page_role='shop')

# ── SHOP ORDERS ───────────────────────────────────────────────────────────────
@app.route('/shop/orders', methods=['GET','POST'])
def shop_orders():
    if not session.get('shop_id'):
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        db.execute('UPDATE orders SET status=? WHERE id=?', (request.form['status'], request.form['order_id']))
        db.commit()
        flash('Order status updated!', 'success')
    orders = db.execute('''
        SELECT o.*, u.name as customer_name, u.phone as customer_phone, u.address as customer_address
        FROM orders o LEFT JOIN users u ON o.user_id = u.id
        ORDER BY o.created_at DESC''').fetchall()
    db.close()
    return render_template('shop_orders.html', orders=orders, page_role='shop')

# ── SHOP BOOKINGS ─────────────────────────────────────────────────────────────
@app.route('/shop/bookings', methods=['GET','POST'])
def shop_bookings():
    if not session.get('shop_id'):
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        db.execute('UPDATE bookings SET status=? WHERE id=?', (request.form['status'], request.form['booking_id']))
        db.commit()
        flash('Booking status updated!', 'success')
    bookings = db.execute('''
        SELECT b.*, u.name as customer_name, u.phone as customer_phone, u.address as customer_address
        FROM bookings b LEFT JOIN users u ON b.user_id = u.id
        ORDER BY b.booking_date DESC''').fetchall()
    db.close()
    return render_template('shop_bookings.html', bookings=bookings, page_role='shop')

# ── SHOP TICKETS ──────────────────────────────────────────────────────────────
@app.route('/shop/tickets', methods=['GET','POST'])
def shop_tickets():
    if not session.get('shop_id'):
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        db.execute('UPDATE tickets SET reply=?, status=? WHERE id=?',
                   (request.form['reply'], 'resolved', request.form['ticket_id']))
        db.commit()
        flash('Reply sent!', 'success')
    tickets = db.execute('''
        SELECT t.*, u.name as customer_name
        FROM tickets t LEFT JOIN users u ON t.user_id = u.id
        ORDER BY t.created_at DESC''').fetchall()
    db.close()
    return render_template('shop_tickets.html', tickets=tickets, page_role='shop')

# ── SHOP INVENTORY ────────────────────────────────────────────────────────────
@app.route('/shop/inventory', methods=['GET','POST'])
def shop_inventory():
    if not session.get('shop_id'):
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name      = request.form['name']
            price     = request.form['price']
            category  = request.form.get('category', '')
            available = 1 if request.form.get('available') else 0
            db.execute('INSERT INTO menu (name,price,category,available) VALUES (?,?,?,?)',
                       (name, price, category, available))
            db.commit()
            flash('Item added to menu!', 'success')
        elif action == 'toggle':
            item_id = request.form['item_id']
            item = db.execute('SELECT available FROM menu WHERE id=?', (item_id,)).fetchone()
            db.execute('UPDATE menu SET available=? WHERE id=?', (0 if item['available'] else 1, item_id))
            db.commit()
            flash('Item availability updated!', 'success')
        elif action == 'delete':
            db.execute('DELETE FROM menu WHERE id=?', (request.form['item_id'],))
            db.commit()
            flash('Item deleted!', 'success')
    menu = db.execute('SELECT * FROM menu ORDER BY category, name').fetchall()
    db.close()
    return render_template('shop_inventory.html', menu=menu, page_role='shop')

if __name__ == '__main__':
    app.run(debug=True)
