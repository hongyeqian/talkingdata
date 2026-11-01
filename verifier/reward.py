"""RLVR verification engine: (task prompt, final answer) -> reward in [0, 1].

Only the final answer is judged; the API call trajectory is ignored.
Ground truth is computed by a trusted reference SQL query (no LLM involved).
"""
import functools
import json
import math
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from rlvr_env import db_init  # noqa: E402
from rlvr_env.tasks import parse_prompt  # noqa: E402

_REFERENCE_SQL = """
WITH target_orders AS (
    SELECT o.order_id FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    JOIN cities ci ON ci.city = c.city
    JOIN membership_tiers t ON t.tier_code = c.tier_code
    WHERE ci.region = ? AND t.is_vip = 1 AND o.status = ?
      AND o.order_date BETWEEN ? AND ?
),
item_total AS (
    SELECT COALESCE(SUM(i.quantity * i.unit_price * (1 - i.discount_rate)), 0) AS v
    FROM order_items i WHERE i.order_id IN (SELECT order_id FROM target_orders)
),
refund_total AS (
    SELECT COALESCE(SUM(r.amount), 0) AS v FROM refunds r
    WHERE r.status = ? AND r.order_id IN (SELECT order_id FROM target_orders)
)
SELECT (SELECT COUNT(*) FROM target_orders), (SELECT v FROM item_total), (SELECT v FROM refund_total)
"""


def _quarter_range(year, quarter):
    m1, m2 = config.QUARTER_MONTHS[quarter]
    last_day = {3: 31, 6: 30, 9: 30, 12: 31}[m2]
    return "%04d-%02d-01" % (year, m1), "%04d-%02d-%02d" % (year, m2, last_day)


@functools.lru_cache(maxsize=256)
def _ground_truth_cached(year, quarter, region, db_path):
    db_init.build(db_path)
    start, end = _quarter_range(year, quarter)
    conn = sqlite3.connect(db_path)
    try:
        count, items, refunds = conn.execute(
            _REFERENCE_SQL,
            (region, config.COMPLETED_STATUS, start, end, config.COUNTED_REFUND_STATUS)).fetchone()
    finally:
        conn.close()
    return {"net_sales": round(items - refunds, config.MONEY_DECIMALS), "order_count": int(count)}


def ground_truth(task_prompt, db_path=None):
    spec = parse_prompt(task_prompt)
    return dict(_ground_truth_cached(spec["year"], spec["quarter"], spec["region"],
                                     db_path or config.DB_PATH))


def parse_answer(answer):
    """Accept a dict, a JSON string, or free text containing a JSON object / <answer> tag."""
    if isinstance(answer, dict):
        return answer
    if not isinstance(answer, str):
        raise ValueError("answer must be a dict or a string")
    m = re.search(r"<answer>(.*?)</answer>", answer, re.S)
    text = m.group(1) if m else answer
    candidates = [text] + re.findall(r"\{[^{}]*\}", text)
    for c in reversed(candidates):  # prefer the last JSON object (the "final" answer)
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            continue
    raise ValueError("no JSON object found in answer")


def _to_number(v):
    if isinstance(v, bool):
        raise ValueError("boolean is not a number")
    if isinstance(v, str):
        v = v.replace(",", "").strip()
    x = float(v)
    if math.isnan(x) or math.isinf(x):
        raise ValueError("non-finite number")
    return x


def score_net_sales(pred, gt):
    denom = max(abs(gt), 1.0)
    rel_err = abs(pred - gt) / denom
    if rel_err <= config.FULL_CREDIT_REL_ERR:
        return 1.0
    if rel_err >= config.ZERO_CREDIT_REL_ERR:
        return 0.0
    span = config.ZERO_CREDIT_REL_ERR - config.FULL_CREDIT_REL_ERR
    return 1.0 - (rel_err - config.FULL_CREDIT_REL_ERR) / span


def score_order_count(pred, gt):
    if pred == gt:
        return 1.0
    tol = max(gt * config.ORDER_COUNT_TOLERANCE_RATIO, 1.0)
    return max(0.0, 1.0 - abs(pred - gt) / tol)


def evaluate(task_prompt, answer, db_path=None):
    """Full evaluation report. Never raises: malformed input yields reward 0 with a reason."""
    report = {"reward": 0.0, "components": {}, "ground_truth": None, "prediction": None, "error": None}
    try:
        gt = ground_truth(task_prompt, db_path)
    except Exception as e:
        report["error"] = "invalid task: %s" % e
        return report
    report["ground_truth"] = gt
    try:
        obj = parse_answer(answer)
        pred = {"net_sales": _to_number(obj["net_sales"]),
                "order_count": _to_number(obj["order_count"])}
    except KeyError as e:
        report["error"] = "missing field %s" % e
        return report
    except Exception as e:
        report["error"] = "invalid answer: %s" % e
        return report
    report["prediction"] = pred
    s_sales = score_net_sales(pred["net_sales"], gt["net_sales"])
    s_count = score_order_count(pred["order_count"], gt["order_count"])
    report["components"] = {"net_sales": round(s_sales, 4), "order_count": round(s_count, 4)}
    reward = config.WEIGHT_NET_SALES * s_sales + config.WEIGHT_ORDER_COUNT * s_count
    report["reward"] = round(min(1.0, max(0.0, reward)), 4)
    return report


def compute_reward(task_prompt, answer, db_path=None):
    """Unified entry point for training harnesses: returns a float in [0, 1]."""
    return evaluate(task_prompt, answer, db_path)["reward"]
