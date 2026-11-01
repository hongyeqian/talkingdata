"""CLI for manual checking.

python -m verifier                                  # print sample tasks and their ground truth
python -m verifier --task "<prompt>" --answer '{"net_sales": 1.0, "order_count": 1}'
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rlvr_env.tasks import SAMPLE_TASKS  # noqa: E402
from verifier.reward import evaluate, ground_truth  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="RLVR verifier: (task, answer) -> reward")
    p.add_argument("--task", help="natural-language task prompt (default: sample task 0)")
    p.add_argument("--answer", help="agent final answer (JSON or text)")
    args = p.parse_args()
    if args.answer is None:
        for t in SAMPLE_TASKS:
            print(json.dumps({"task": t, "ground_truth": ground_truth(t)}, ensure_ascii=False))
        return
    print(json.dumps(evaluate(args.task or SAMPLE_TASKS[0], args.answer), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
