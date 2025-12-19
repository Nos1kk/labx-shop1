import sqlite3

DB_NAME = "shop.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Таблица заказов
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        type TEXT,
        item_name TEXT,
        description TEXT,
        user_file TEXT DEFAULT '',
        price INTEGER DEFAULT 0,
        status TEXT DEFAULT 'wait_price',
        admin_comment TEXT DEFAULT '',
        is_paid BOOLEAN DEFAULT 0,
        discount INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # Файлы к заказам
    c.execute('''CREATE TABLE IF NOT EXISTS order_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        file_name TEXT,
        file_url TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # Чат поддержки
    c.execute('''CREATE TABLE IF NOT EXISTS support_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT DEFAULT '',
        sender TEXT,
        message TEXT,
        file_url TEXT DEFAULT '',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_read BOOLEAN DEFAULT 0
    )''')
    
    # Промокоды
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        discount INTEGER DEFAULT 10,
        uses_left INTEGER DEFAULT 1,
        is_active BOOLEAN DEFAULT 1
    )''')
    
    # Тестовые промокоды
    try:
        c.execute("INSERT OR IGNORE INTO promo_codes (code, discount, uses_left) VALUES ('LABX10', 10, 100)")
        c.execute("INSERT OR IGNORE INTO promo_codes (code, discount, uses_left) VALUES ('LABX20', 20, 50)")
        c.execute("INSERT OR IGNORE INTO promo_codes (code, discount, uses_left) VALUES ('FIRST', 15, 999)")
    except:
        pass
    
    conn.commit()
    conn.close()


# ========== ЗАКАЗЫ ==========

def add_order(user_id, username, order_type, item_name, description, user_file='', discount=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO orders (user_id, username, type, item_name, description, user_file, discount) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username, order_type, item_name, description, user_file, discount))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_orders(user_id=None):
    conn = get_connection()
    c = conn.cursor()
    if user_id:
        c.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,))
    else:
        c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def update_order(order_id, price, status, admin_comment, is_paid):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE orders 
        SET price=?, status=?, admin_comment=?, is_paid=?
        WHERE id=?
    """, (price, status, admin_comment, is_paid, order_id))
    conn.commit()
    conn.close()


def delete_order(order_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM orders WHERE id=?", (order_id,))
    c.execute("DELETE FROM order_files WHERE order_id=?", (order_id,))
    conn.commit()
    conn.close()


# ========== ФАЙЛЫ ЗАКАЗОВ ==========

def add_order_file(order_id, file_name, file_url):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO order_files (order_id, file_name, file_url) VALUES (?, ?, ?)",
              (order_id, file_name, file_url))
    conn.commit()
    conn.close()


def get_order_files(order_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM order_files WHERE order_id = ?", (order_id,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


# ========== ПРОМОКОДЫ ==========

def get_promo(code):
    if not code:
        return None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM promo_codes WHERE code = ? AND is_active = 1", (code.upper(),))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except:
        return None


def use_promo(code):
    if not code:
        return
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code.upper(),))
        conn.commit()
        conn.close()
    except:
        pass


# ========== ЧАТ ==========

def add_chat_message(user_id, sender, message, file_url='', username=''):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO support_chat (user_id, username, sender, message, file_url) 
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, sender, message, file_url))
    conn.commit()
    conn.close()


def get_chat_history(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM support_chat WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_all_chats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, username, message, timestamp, 
               (SELECT COUNT(*) FROM support_chat s2 
                WHERE s2.user_id = s1.user_id AND s2.is_read = 0 AND s2.sender = 'user') as unread
        FROM support_chat s1
        WHERE id IN (SELECT MAX(id) FROM support_chat GROUP BY user_id)
        ORDER BY timestamp DESC
    """)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def mark_chat_as_read(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE support_chat SET is_read = 1 WHERE user_id = ? AND sender = 'user'", (user_id,))
    conn.commit()
    conn.close()