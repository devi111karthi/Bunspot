import sqlite3, os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'bunspot.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.executescript('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    role TEXT DEFAULT 'customer'
);

CREATE TABLE IF NOT EXISTS menu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    category TEXT,
    available INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_name TEXT,
    quantity INTEGER,
    price REAL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    booking_date TEXT,
    booking_time TEXT,
    guests INTEGER,
    note TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    subject TEXT,
    message TEXT,
    reply TEXT,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')

c.execute("SELECT * FROM users WHERE email='owner@bunspot.in'")
if not c.fetchone():
    c.execute("INSERT INTO users (name,email,password,phone,address,role) VALUES (?,?,?,?,?,?)",
              ('BunSpot Owner','owner@bunspot.in',generate_password_hash('owner123'),'9999999999','BunSpot HQ','owner'))

c.execute("SELECT COUNT(*) FROM menu")
if c.fetchone()[0] == 0:
    items = [
        ('Veg Burger',120,'Burger'),('Chicken Burger',80,'Burger'),
        ('Paneer Wrap',90,'Wrap'),('Chicken Wrap',110,'Wrap'),
        ('French Fries',60,'Snacks'),('Onion Rings',50,'Snacks'),
        ('Cold Coffee',70,'Drinks'),('Mango Shake',80,'Drinks'),
        ('Masala Chai',30,'Drinks'),('Veg Pizza',150,'Pizza'),
        ('Chicken Pizza',180,'Pizza'),
    ]
    c.executemany("INSERT INTO menu (name,price,category,available) VALUES (?,?,?,1)", items)

conn.commit(); conn.close()
print("Database ready! Login: owner@bunspot.in / owner123")
