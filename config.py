"""Global configuration: paths, business rules, API limits and reward thresholds.

All tunable rules live here so the environment and the verifier stay in sync.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RLVR_DB_PATH", os.path.join(BASE_DIR, "data", "shop.db"))

# ---------------------------------------------------------------- data generation
RANDOM_SEED = 20261101
DATA_YEAR = 2026
NUM_CUSTOMERS = 400
NUM_PRODUCTS = 60
NUM_ORDERS = 5000

REGION_CITIES = {
    "华东": ["上海", "杭州", "南京", "苏州", "合肥", "厦门"],
    "华北": ["北京", "天津", "石家庄", "太原"],
    "华南": ["广州", "深圳", "南宁", "海口"],
    "西南": ["成都", "重庆", "昆明", "贵阳"],
}

# (code, display name, level, is_vip). "VIP" is defined by the is_vip flag,
# NOT by level: the internal "staff" tier has the highest level but is not VIP.
MEMBERSHIP_TIERS = [
    ("T1", "普通会员", 1, 0),
    ("T2", "银卡会员", 2, 0),
    ("T3", "金卡会员", 3, 1),
    ("T4", "黑钻会员", 4, 1),
    ("T9", "内部员工", 9, 0),
]

ORDER_STATUSES = ["completed", "cancelled", "pending_payment", "shipped", "closed"]
ORDER_STATUS_WEIGHTS = [0.62, 0.12, 0.08, 0.12, 0.06]
REFUND_STATUSES = ["approved", "rejected", "processing"]
REFUND_STATUS_WEIGHTS = [0.6, 0.25, 0.15]
REFUND_RATE = 0.3  # share of orders that get a refund request
DISCOUNT_CHOICES = [0.0, 0.0, 0.05, 0.1, 0.15, 0.2]

# ---------------------------------------------------------------- business rules
# Hidden constraints the agent must infer from the natural-language task.
COMPLETED_STATUS = "completed"          # "已完成订单"
COUNTED_REFUND_STATUS = "approved"      # only approved refunds reduce revenue
QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
MONEY_DECIMALS = 2

# ---------------------------------------------------------------- API limits
MAX_PAGE_SIZE = 100          # get_orders pagination
MAX_IDS_PER_CALL = 100       # batch size for id-list parameters

# ---------------------------------------------------------------- reward
# net_sales: full credit within FULL_CREDIT_REL_ERR, linear decay to 0 at ZERO_CREDIT_REL_ERR
FULL_CREDIT_REL_ERR = 0.001
ZERO_CREDIT_REL_ERR = 0.02
WEIGHT_NET_SALES = 0.8
WEIGHT_ORDER_COUNT = 0.2
# order_count: credit = max(0, 1 - |diff| / (gt * ORDER_COUNT_TOLERANCE_RATIO))
ORDER_COUNT_TOLERANCE_RATIO = 0.2
