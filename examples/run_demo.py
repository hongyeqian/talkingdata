"""Demo: standard usage of the environment APIs and the verification engine.

A scripted "agent" solves the task purely through the business APIs (the typical
execution path), then the verifier scores a correct answer and several wrong ones.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from rlvr_env.api import ShopEnv  # noqa: E402
from rlvr_env.tasks import SAMPLE_TASKS, parse_prompt  # noqa: E402
from verifier import compute_reward, evaluate  # noqa: E402


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def must(resp):
    if not resp["ok"]:
        raise RuntimeError(resp["error"])
    return resp["data"]


def scripted_agent(env, prompt, vip_rule="is_vip", status="completed", refund_status="approved"):
    """Solve via APIs only. The keyword args let us inject typical agent mistakes."""
    spec = parse_prompt(prompt)  # in real training, the LLM does this "reading"
    m1, m2 = config.QUARTER_MONTHS[spec["quarter"]]
    start = "%d-%02d-01" % (spec["year"], m1)
    end = "%d-%02d-%02d" % (spec["year"], m2, {3: 31, 6: 30, 9: 30, 12: 31}[m2])

    # Step 1: which tiers are VIP?  (hidden constraint: is_vip flag, not tier level)
    tiers = must(env.get_membership_tiers())
    if vip_rule == "is_vip":
        vip = [t["tier_code"] for t in tiers if t["is_vip"]]
    else:  # mistake: "level >= 3" also catches the internal staff tier
        vip = [t["tier_code"] for t in tiers if t["level"] >= 3]
    # Step 2: region -> cities
    cities = must(env.get_region_cities(spec["region"]))
    # Step 3: target customers
    customers = must(env.list_customers(cities=cities, tier_codes=vip))
    cids = [c["customer_id"] for c in customers]
    # Step 4: completed orders in the quarter (batched + paginated)
    order_ids = []
    for batch in chunks(cids, config.MAX_IDS_PER_CALL):
        page = 1
        while True:
            data = must(env.get_orders(customer_ids=batch, start_date=start, end_date=end,
                                       status=status, page=page, page_size=config.MAX_PAGE_SIZE))
            order_ids += [o["order_id"] for o in data["orders"]]
            if page * data["page_size"] >= data["total"]:
                break
            page += 1
    # Step 5 + 6: line items and refunds, then aggregate
    gross = refund = 0.0
    for batch in chunks(order_ids, config.MAX_IDS_PER_CALL):
        for it in must(env.get_order_items(order_ids=batch)):
            gross += it["quantity"] * it["unit_price"] * (1 - it["discount_rate"])
        for r in must(env.get_refunds(order_ids=batch)):
            if refund_status is None or r["status"] == refund_status:
                refund += r["amount"]
    return json.dumps({"net_sales": round(gross - refund, 2), "order_count": len(order_ids)})


def main():
    env = ShopEnv()
    print("=" * 72)
    print("Available APIs:", env.tool_names())
    print("Error handling demo:", env.call("get_orders", customer_ids="abc", start_date="2026-07-01",
                                          end_date="2026-09-30"))
    print("Unknown API demo  :", env.call("drop_table"))

    task = SAMPLE_TASKS[0]
    print("=" * 72)
    print("TASK:", task)
    env.reset()
    correct = scripted_agent(env, task)
    print("API calls used by reference path: %d -> %s"
          % (len(env.call_log), sorted({c["api"] for c in env.call_log})))

    scenarios = [
        ("correct answer (reference path)", correct),
        ("correct answer wrapped in text", "分析完成。<answer>%s</answer>" % correct),
        ("WRONG: VIP judged by level>=3 (includes staff)", scripted_agent(env, task, vip_rule="level")),
        ("WRONG: counted all refund requests", scripted_agent(env, task, refund_status=None)),
        ("WRONG: used shipped instead of completed", scripted_agent(env, task, status="shipped")),
        ("WRONG: platform-wide GMV shortcut",
         json.dumps({"net_sales": must(env.get_sales_summary(2026, 7))["gmv"], "order_count": 999})),
        ("INVALID: malformed answer", "I think the answer is about 1 million"),
        ("INVALID: missing field", {"net_sales": 1.0}),
    ]
    results = []
    for name, ans in scenarios:
        rep = evaluate(task, ans)
        results.append((name, rep["reward"]))
        print("-" * 72)
        print("[%s] reward=%.4f" % (name, rep["reward"]))
        print("   prediction=%s ground_truth=%s components=%s error=%s"
              % (rep["prediction"], rep["ground_truth"], rep["components"], rep["error"]))

    print("=" * 72)
    print("Other sample tasks (reference path should always score 1.0):")
    for t in SAMPLE_TASKS[1:]:
        print("  reward=%.4f  %s" % (compute_reward(t, scripted_agent(env, t)), parse_prompt(t)))
    print("Invalid task prompt -> reward=%.1f" % compute_reward("随便算点什么", correct))
    print("=" * 72)
    print("SUMMARY")
    for name, r in results:
        print("  %.4f  %s" % (r, name))
    env.close()


if __name__ == "__main__":
    main()
