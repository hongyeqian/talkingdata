"""Business API environment exposed to the agent.

The agent may only call the public methods below (or `call(name, **kwargs)`).
Every method returns {"ok": True, "data": ...} or {"ok": False, "error": "..."}
and never raises, so a bad tool call cannot crash the training loop.
"""
import datetime as dt
import functools
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from rlvr_env import db_init  # noqa: E402


class ApiError(ValueError):
    pass


def _tool(fn):
    """Wrap a method: record the call, convert exceptions into error payloads."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        self.call_log.append({"api": fn.__name__, "args": list(args), "kwargs": kwargs})
        try:
            return {"ok": True, "data": fn(self, *args, **kwargs)}
        except ApiError as e:
            return {"ok": False, "error": str(e)}
        except TypeError as e:
            return {"ok": False, "error": "bad arguments: %s" % e}
        except Exception as e:  # pragma: no cover - defensive
            return {"ok": False, "error": "internal error: %s" % type(e).__name__}
    wrapper.is_tool = True
    return wrapper


def _check_date(value, name):
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ApiError("%s must be YYYY-MM-DD, got %r" % (name, value))


def _check_ids(ids, name):
    if not isinstance(ids, (list, tuple)) or not ids:
        raise ApiError("%s must be a non-empty list of integers" % name)
    if len(ids) > config.MAX_IDS_PER_CALL:
        raise ApiError("%s accepts at most %d ids per call" % (name, config.MAX_IDS_PER_CALL))
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ApiError("%s must contain integers only" % name)
    return list(ids)


class ShopEnv:
    """E-commerce analytics environment backed by SQLite (read-only for the agent)."""

    def __init__(self, db_path=config.DB_PATH):
        db_init.build(db_path)  # no-op if the DB already exists
        uri = "file:%s?mode=ro" % os.path.abspath(db_path)
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.call_log = []

    # ------------------------------------------------------------ helpers
    def _q(self, sql, params=()):
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def reset(self):
        self.call_log = []

    def close(self):
        self._conn.close()

    @classmethod
    def tool_names(cls):
        return sorted(n for n, f in vars(cls).items() if getattr(f, "is_tool", False))

    def call(self, name, **kwargs):
        """Generic dispatcher for harnesses that emit (tool_name, arguments)."""
        if name not in self.tool_names():
            self.call_log.append({"api": name, "kwargs": kwargs})
            return {"ok": False, "error": "unknown api %r, available: %s" % (name, self.tool_names())}
        return getattr(self, name)(**kwargs)

    # ------------------------------------------------------------ business APIs
    @_tool
    def get_membership_tiers(self):
        """List membership tiers with level and VIP flag."""
        return self._q("SELECT tier_code, tier_name, level, is_vip FROM membership_tiers ORDER BY level")

    @_tool
    def get_region_cities(self, region):
        """Return the cities belonging to a sales region (e.g. '华东')."""
        rows = self._q("SELECT city FROM cities WHERE region = ? ORDER BY city", (region,))
        if not rows:
            regions = [r["region"] for r in self._q("SELECT DISTINCT region FROM cities")]
            raise ApiError("unknown region %r, valid regions: %s" % (region, regions))
        return [r["city"] for r in rows]

    @_tool
    def list_customers(self, cities=None, tier_codes=None):
        """Customers filtered by city list and/or tier code list."""
        sql, params = "SELECT customer_id, name, city, tier_code, phone, email, registered_at FROM customers WHERE 1=1", []
        for col, vals in (("city", cities), ("tier_code", tier_codes)):
            if vals is not None:
                if not isinstance(vals, (list, tuple)) or not vals:
                    raise ApiError("%s must be a non-empty list" % col)
                sql += " AND %s IN (%s)" % (col, ",".join("?" * len(vals)))
                params.extend(vals)
        if cities is None and tier_codes is None:
            raise ApiError("provide at least one filter: cities or tier_codes")
        return self._q(sql + " ORDER BY customer_id", params)

    @_tool
    def get_orders(self, customer_ids, start_date, end_date, status=None, page=1, page_size=50):
        """Orders of the given customers with start_date <= order_date <= end_date (paginated)."""
        ids = _check_ids(customer_ids, "customer_ids")
        s, e = _check_date(start_date, "start_date"), _check_date(end_date, "end_date")
        if s > e:
            raise ApiError("start_date must not be after end_date")
        if not isinstance(page, int) or page < 1:
            raise ApiError("page must be a positive integer")
        if not isinstance(page_size, int) or not 1 <= page_size <= config.MAX_PAGE_SIZE:
            raise ApiError("page_size must be in [1, %d]" % config.MAX_PAGE_SIZE)
        where = "customer_id IN (%s) AND order_date BETWEEN ? AND ?" % ",".join("?" * len(ids))
        params = ids + [s, e]
        if status is not None:
            if status not in config.ORDER_STATUSES:
                raise ApiError("status must be one of %s" % config.ORDER_STATUSES)
            where += " AND status = ?"
            params.append(status)
        total = self._conn.execute("SELECT COUNT(*) FROM orders WHERE " + where, params).fetchone()[0]
        rows = self._q("SELECT * FROM orders WHERE %s ORDER BY order_id LIMIT ? OFFSET ?" % where,
                       params + [page_size, (page - 1) * page_size])
        return {"total": total, "page": page, "page_size": page_size, "orders": rows}

    @_tool
    def get_order_items(self, order_ids):
        """Line items (quantity, actual unit_price, discount_rate) of the given orders."""
        ids = _check_ids(order_ids, "order_ids")
        return self._q("SELECT * FROM order_items WHERE order_id IN (%s) ORDER BY item_id"
                       % ",".join("?" * len(ids)), ids)

    @_tool
    def get_refunds(self, order_ids):
        """Refund requests (any status) of the given orders."""
        ids = _check_ids(order_ids, "order_ids")
        return self._q("SELECT * FROM refunds WHERE order_id IN (%s) ORDER BY refund_id"
                       % ",".join("?" * len(ids)), ids)

    # ------------------------------------------------------------ distractor APIs
    @_tool
    def get_product_info(self, product_ids):
        """Catalogue info. NOTE: list_price is the catalogue price, not the transaction price."""
        ids = _check_ids(product_ids, "product_ids")
        return self._q("SELECT * FROM products WHERE product_id IN (%s)" % ",".join("?" * len(ids)), ids)

    @_tool
    def get_product_reviews(self, product_id, limit=20):
        if not isinstance(product_id, int):
            raise ApiError("product_id must be an integer")
        return self._q("SELECT * FROM product_reviews WHERE product_id = ? LIMIT ?",
                       (product_id, max(1, min(int(limit), 100))))

    @_tool
    def get_warehouse_stock(self, warehouse):
        if warehouse not in ("WH-SH", "WH-BJ", "WH-GZ"):
            raise ApiError("warehouse must be one of WH-SH, WH-BJ, WH-GZ")
        return self._q("SELECT product_id, name, stock FROM products ORDER BY product_id")

    @_tool
    def get_sales_summary(self, year, month):
        """Platform-wide GMV (all regions, all statuses, before refunds) - a tempting shortcut."""
        if not (isinstance(year, int) and isinstance(month, int) and 1 <= month <= 12):
            raise ApiError("year/month must be integers, month in 1..12")
        prefix = "%04d-%02d" % (year, month)
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT o.order_id), ROUND(SUM(i.quantity * i.unit_price), 2) FROM orders o "
            "JOIN order_items i ON o.order_id = i.order_id WHERE substr(o.order_date, 1, 7) = ?",
            (prefix,)).fetchone()
        return {"month": prefix, "order_count": row[0], "gmv": row[1] or 0.0}
