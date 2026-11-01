"""Deterministically build the simulated e-commerce SQLite database.

Usage: python -m rlvr_env.db_init [--force]
"""
import datetime as dt
import os
import random
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

SCHEMA = """
CREATE TABLE membership_tiers (
    tier_code TEXT PRIMARY KEY, tier_name TEXT, level INTEGER, is_vip INTEGER);
CREATE TABLE cities (city TEXT PRIMARY KEY, region TEXT);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY, name TEXT, city TEXT, tier_code TEXT,
    phone TEXT, email TEXT, registered_at TEXT);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY, name TEXT, category TEXT, list_price REAL,
    cost_price REAL, stock INTEGER, rating REAL);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date TEXT, status TEXT,
    shipping_fee REAL, payment_method TEXT, warehouse TEXT);
CREATE TABLE order_items (
    item_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, quantity INTEGER,
    unit_price REAL, discount_rate REAL);
CREATE TABLE refunds (
    refund_id INTEGER PRIMARY KEY, order_id INTEGER, amount REAL, status TEXT,
    reason TEXT, requested_at TEXT);
CREATE TABLE product_reviews (
    review_id INTEGER PRIMARY KEY, product_id INTEGER, customer_id INTEGER,
    score INTEGER, content TEXT);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_refunds_order ON refunds(order_id);
"""

CATEGORIES = ["数码", "家电", "服饰", "美妆", "食品", "图书"]
SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜"
GIVEN = "伟芳娜敏静丽强磊军洋勇艳杰娟涛明超秀霞平刚桂英华"


def build(db_path=config.DB_PATH, force=False):
    if os.path.exists(db_path):
        if not force:
            return db_path
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    rng = random.Random(config.RANDOM_SEED)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    cur.executemany("INSERT INTO membership_tiers VALUES (?,?,?,?)", config.MEMBERSHIP_TIERS)
    all_cities = []
    for region, cities in config.REGION_CITIES.items():
        for c in cities:
            cur.execute("INSERT INTO cities VALUES (?,?)", (c, region))
            all_cities.append(c)

    tier_codes = [t[0] for t in config.MEMBERSHIP_TIERS]
    tier_weights = [0.4, 0.27, 0.18, 0.08, 0.07]
    for cid in range(1, config.NUM_CUSTOMERS + 1):
        name = rng.choice(SURNAMES) + rng.choice(GIVEN) + rng.choice(GIVEN)
        cur.execute(
            "INSERT INTO customers VALUES (?,?,?,?,?,?,?)",
            (cid, name, rng.choice(all_cities), rng.choices(tier_codes, tier_weights)[0],
             "1%010d" % rng.randrange(10 ** 10), "user%d@example.com" % cid,
             "%d-%02d-%02d" % (rng.randint(2020, 2025), rng.randint(1, 12), rng.randint(1, 28))))

    for pid in range(1, config.NUM_PRODUCTS + 1):
        price = round(rng.uniform(19, 2999), 2)
        cur.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
            (pid, "商品%03d" % pid, rng.choice(CATEGORIES), price,
             round(price * rng.uniform(0.4, 0.8), 2), rng.randint(0, 500),
             round(rng.uniform(3, 5), 1)))
    list_prices = dict(cur.execute("SELECT product_id, list_price FROM products").fetchall())

    start = dt.date(config.DATA_YEAR, 1, 1)
    item_id = refund_id = 0
    for oid in range(1, config.NUM_ORDERS + 1):
        day = start + dt.timedelta(days=rng.randrange(365))
        status = rng.choices(config.ORDER_STATUSES, config.ORDER_STATUS_WEIGHTS)[0]
        cur.execute(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?)",
            (oid, rng.randint(1, config.NUM_CUSTOMERS), day.isoformat(), status,
             rng.choice([0.0, 6.0, 10.0, 15.0]), rng.choice(["alipay", "wechat", "card"]),
             rng.choice(["WH-SH", "WH-BJ", "WH-GZ"])))
        order_total = 0.0
        for pid in rng.sample(range(1, config.NUM_PRODUCTS + 1), rng.randint(1, 4)):
            item_id += 1
            qty = rng.randint(1, 5)
            # actual transaction price drifts from the catalogue list price
            unit_price = round(list_prices[pid] * rng.uniform(0.85, 1.05), 2)
            disc = rng.choice(config.DISCOUNT_CHOICES)
            order_total += qty * unit_price * (1 - disc)
            cur.execute("INSERT INTO order_items VALUES (?,?,?,?,?,?)",
                        (item_id, oid, pid, qty, unit_price, disc))
        if rng.random() < config.REFUND_RATE:
            refund_id += 1
            cur.execute(
                "INSERT INTO refunds VALUES (?,?,?,?,?,?)",
                (refund_id, oid, round(order_total * rng.uniform(0.1, 1.0), 2),
                 rng.choices(config.REFUND_STATUSES, config.REFUND_STATUS_WEIGHTS)[0],
                 rng.choice(["质量问题", "不想要了", "发错货", "物流太慢"]),
                 (day + dt.timedelta(days=rng.randint(1, 20))).isoformat()))

    for rid in range(1, 1501):
        cur.execute("INSERT INTO product_reviews VALUES (?,?,?,?,?)",
                    (rid, rng.randint(1, config.NUM_PRODUCTS), rng.randint(1, config.NUM_CUSTOMERS),
                     rng.randint(1, 5), rng.choice(["很好", "一般", "物流快", "质量差", "推荐"])))
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = build(force="--force" in sys.argv)
    print("database ready:", path)
