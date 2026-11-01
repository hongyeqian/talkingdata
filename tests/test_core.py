import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from examples.run_demo import scripted_agent  # noqa: E402
from rlvr_env.api import ShopEnv  # noqa: E402
from rlvr_env.tasks import SAMPLE_TASKS, make_prompt  # noqa: E402
from verifier import compute_reward, ground_truth  # noqa: E402


class CoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = ShopEnv()

    def test_reference_path_scores_one(self):
        for t in SAMPLE_TASKS:
            self.assertEqual(compute_reward(t, scripted_agent(self.env, t)), 1.0)

    def test_reward_range_and_monotonic(self):
        t = SAMPLE_TASKS[0]
        gt = ground_truth(t)
        rewards = [compute_reward(t, {"net_sales": gt["net_sales"] * (1 + e), "order_count": gt["order_count"]})
                   for e in (0, 0.005, 0.01, 0.05)]
        self.assertTrue(all(0 <= r <= 1 for r in rewards))
        self.assertEqual(rewards, sorted(rewards, reverse=True))

    def test_bad_inputs_never_raise(self):
        t = SAMPLE_TASKS[0]
        for ans in (None, 123, "", "{}", '{"net_sales": "NaN", "order_count": 1}', [1, 2], {"net_sales": True, "order_count": 1}):
            self.assertEqual(compute_reward(t, ans), 0.0)
        self.assertEqual(compute_reward(None, "{}"), 0.0)

    def test_api_validation(self):
        self.assertFalse(self.env.get_orders(customer_ids=[1], start_date="2026-13-01", end_date="2026-12-31")["ok"])
        self.assertFalse(self.env.get_orders(customer_ids=list(range(500)), start_date="2026-01-01", end_date="2026-12-31")["ok"])
        self.assertFalse(self.env.get_region_cities("火星")["ok"])
        self.assertFalse(self.env.call("get_orders", foo=1)["ok"])
        self.assertFalse(self.env.call("not_exist")["ok"])

    def test_chinese_quarter_prompt(self):
        p = make_prompt(2026, 3, "华东").replace("第3季度", "第三季度")
        self.assertEqual(ground_truth(p), ground_truth(SAMPLE_TASKS[0]))


if __name__ == "__main__":
    unittest.main()
