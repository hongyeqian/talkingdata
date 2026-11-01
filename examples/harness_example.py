"""Minimal training-harness integration example (one episode).

A real harness would let the policy LLM choose each (tool_name, arguments).
Here a fixed action list stands in for the policy, to show the calling contract:
    env.call(name, **kwargs) -> {"ok": bool, "data"/"error": ...}
    compute_reward(task_prompt, final_answer) -> float in [0, 1]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rlvr_env.api import ShopEnv  # noqa: E402
from rlvr_env.tasks import make_prompt  # noqa: E402
from verifier import compute_reward  # noqa: E402


def run_episode():
    env = ShopEnv()
    prompt = make_prompt(2026, 3, "华东")
    print("TASK:", prompt)

    # --- policy rollout (stand-in): tool calls emitted as (name, arguments) ---
    tiers = env.call("get_membership_tiers")["data"]
    vip = [t["tier_code"] for t in tiers if t["is_vip"]]
    cities = env.call("get_region_cities", region="华东")["data"]
    cids = [c["customer_id"] for c in env.call("list_customers", cities=cities, tier_codes=vip)["data"]]
    orders = env.call("get_orders", customer_ids=cids, start_date="2026-07-01", end_date="2026-09-30",
                      status="completed", page_size=100)["data"]
    oids = [o["order_id"] for o in orders["orders"]]  # total <= 100 here, so one page is enough
    items = env.call("get_order_items", order_ids=oids)["data"]
    refunds = env.call("get_refunds", order_ids=oids)["data"]
    bad = env.call("get_orders", customer_ids=[], start_date="x", end_date="y")  # a failed call is harmless

    net = sum(i["quantity"] * i["unit_price"] * (1 - i["discount_rate"]) for i in items) \
        - sum(r["amount"] for r in refunds if r["status"] == "approved")
    final_answer = "<answer>%s</answer>" % json.dumps({"net_sales": round(net, 2), "order_count": len(oids)})

    for c in env.call_log:
        print("  tool call:", c["api"])
    print("  failed call example:", bad)
    print("FINAL ANSWER:", final_answer)
    print("REWARD:", compute_reward(prompt, final_answer))
    env.close()


if __name__ == "__main__":
    run_episode()
