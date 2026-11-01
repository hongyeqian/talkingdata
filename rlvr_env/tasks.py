"""Task definitions: natural-language prompt template, parser and sample tasks."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

PROMPT_TEMPLATE = (
    "请统计{year}年第{quarter}季度{region}地区 VIP 客户的已完成订单的净销售额与订单数。"
    "净销售额 = 商品实际成交金额（扣除折扣）- 退款，不含运费。"
    "请仅通过提供的业务 API 获取数据，最终以 JSON 输出："
    '{{"net_sales": <保留两位小数的数值>, "order_count": <整数>}}'
)

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4}


def make_prompt(year, quarter, region):
    return PROMPT_TEMPLATE.format(year=year, quarter=quarter, region=region)


def parse_prompt(prompt):
    """Extract the task spec {year, quarter, region} from a prompt. Raises ValueError."""
    if not isinstance(prompt, str):
        raise ValueError("task prompt must be a string")
    m = re.search(r"(\d{4})\s*年\s*第\s*([1-4一二三四])\s*季度", prompt)
    if not m:
        raise ValueError("cannot find '<year>年第<N>季度' in task prompt")
    q = m.group(2)
    regions = [r for r in config.REGION_CITIES if r in prompt]
    if len(regions) != 1:
        raise ValueError("task prompt must mention exactly one region of %s" % list(config.REGION_CITIES))
    return {"year": int(m.group(1)), "quarter": _CN_NUM.get(q) or int(q), "region": regions[0]}


SAMPLE_TASKS = [
    make_prompt(2026, 3, "华东"),
    make_prompt(2026, 1, "华北"),
    make_prompt(2026, 4, "华南"),
]
