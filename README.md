# 电商订单分析 RLVR 任务环境

**所选题目：题目一，复杂业务分析 RLVR 任务构建**

这是一个单场景的 RLVR 任务单元，包含三部分：

- 用 SQLite 模拟电商业务数据，智能体只能通过 Python 类方法形式的业务 API 访问
- 一个多步分析任务：统计某季度、某地区 VIP 客户已完成订单的净销售额和订单数
- 一个独立的验证引擎：输入任务和最终答案，输出 0～1 的奖励，不调用任何大模型

整个项目只用 Python 标准库（3.8+），无第三方依赖。

## 1. 目录结构

```
.
├── config.py              # 统一配置：数据规模、业务规则、API 限制、奖励阈值
├── rlvr_env/
│   ├── db_init.py         # 用固定随机种子生成 SQLite 数据（可复现）
│   ├── api.py             # ShopEnv：业务 API（智能体唯一的数据入口）
│   └── tasks.py           # 任务模板、自然语言任务解析、样例任务
├── verifier/
│   ├── __init__.py        # 导出 compute_reward / evaluate / ground_truth
│   └── reward.py          # 验证引擎：参考 SQL 算真值 + 奖励函数
├── examples/run_demo.py   # 调用样例：1 条正确路径 + 多个错误场景
├── tests/test_core.py     # 单元测试
├── data/                  # shop.db 生成位置（不提交，运行时自动生成）
├── Dockerfile
└── requirements.txt
```

环境、验证器、配置和样例四部分互相独立。验证器不依赖 `ShopEnv`，直接用可信的参考 SQL 计算真值。

## 2. 运行方式

### 本地运行

```bash
python3 -m rlvr_env.db_init --force
```

```bash
python3 examples/run_demo.py
```

```bash
python3 -m unittest discover -s tests -v
```

不先跑 `db_init` 也可以：数据库不存在时，`ShopEnv` 和验证器会自动生成。

### Docker

```bash
docker build -t rlvr-shop .
```

```bash
docker run --rm rlvr-shop
```

镜像里已经包含代码和生成好的数据库。容器启动后会自动运行 `examples/run_demo.py`，打印每个场景的奖励。

把本地目录挂载进容器，供训练框架加载：

```bash
docker run --rm -v "$PWD":/workspace -w /workspace -e PYTHONPATH=/workspace rlvr-shop \
  python -c "from verifier import compute_reward; from rlvr_env.tasks import SAMPLE_TASKS; print(compute_reward(SAMPLE_TASKS[0], '{\"net_sales\": 1, \"order_count\": 1}'))"
```

在容器里运行测试：

```bash
docker run --rm rlvr-shop python -m unittest discover -s tests
```

## 3. 任务设计

### 自然语言输入

```
请统计2026年第3季度华东地区 VIP 客户的已完成订单的净销售额与订单数。
净销售额 = 商品实际成交金额（扣除折扣）- 退款，不含运费。
请仅通过提供的业务 API 获取数据，最终以 JSON 输出：
{"net_sales": <保留两位小数的数值>, "order_count": <整数>}
```

年份、季度（`3` 或 `三` 都能识别）、地区（华东 / 华北 / 华南 / 西南）都是参数，用 `rlvr_env.tasks.make_prompt(year, quarter, region)` 可以批量生成任务。

### 输出格式

输出一个 JSON 对象：`{"net_sales": float, "order_count": int}`。验证器也能从自由文本里提取答案，例如 `<answer>{...}</answer>`；文本中有多个 JSON 对象时，取最后一个。

### 成功判定

- `net_sales` 与真值的相对误差 ≤ 0.1%
- `order_count` 与真值完全一致

两项都满足时奖励为 1.0。

### 隐含业务约束（题面不直接给出，需要智能体推导）

| 题面说法 | 正确的查询条件 | 常见陷阱 |
|---|---|---|
| VIP 客户 | 调用 `get_membership_tiers`，取 `is_vip=1` 的等级（T3、T4） | 按 `level>=3` 筛选，会把 level=9 的"内部员工"也算进来 |
| 华东地区 | 调用 `get_region_cities` 把地区换成城市列表；客户表里只有 `city` 字段 | 直接按"华东"筛客户，查不到结果 |
| 第 3 季度 | 换算成 `2026-07-01` 到 `2026-09-30` | 月份边界算错 |
| 已完成订单 | `status='completed'` | 把 `shipped`（已发货）也算进去 |
| 商品实际成交金额 | `order_items.quantity × unit_price × (1 - discount_rate)` | 误用 `get_product_info` 返回的 `list_price`（目录价） |
| 退款 | 只扣除 `status='approved'` 的退款 | 把 rejected / processing 的退款申请也扣掉 |
| 不含运费 | 忽略 `orders.shipping_fee` | 把运费加进去 |

### 冗余 API 与非必要字段

- 冗余 API：`get_product_info`、`get_product_reviews`、`get_warehouse_stock`、`get_sales_summary`
- `get_sales_summary` 返回全平台月度 GMV，看起来像捷径，实际上范围（全地区、全状态、未扣退款）完全不对
- 非必要字段：`phone`、`email`、`registered_at`、`payment_method`、`warehouse`、`shipping_fee`、`cost_price` 等

## 4. 接口定义（`rlvr_env.api.ShopEnv`）

所有 API 都返回 `{"ok": True, "data": ...}` 或 `{"ok": False, "error": "..."}`，不会抛出异常。参数非法、调用不存在的 API 时，也只返回错误信息，不会中断训练流程。每次调用都会记录到 `env.call_log`。

| API | 参数 | 返回 | 是否必要 |
|---|---|---|---|
| `get_membership_tiers()` | 无 | 等级列表 `[{tier_code, tier_name, level, is_vip}]` | 必要 |
| `get_region_cities(region)` | 地区名 | 城市列表 | 必要 |
| `list_customers(cities=None, tier_codes=None)` | 至少传一个过滤条件 | 客户列表 | 必要 |
| `get_orders(customer_ids, start_date, end_date, status=None, page=1, page_size=50)` | 每次最多 100 个 ID；`page_size` ≤ 100 | `{total, page, page_size, orders}` | 必要 |
| `get_order_items(order_ids)` | 每次最多 100 个 ID | 订单明细：数量、成交单价、折扣率 | 必要 |
| `get_refunds(order_ids)` | 每次最多 100 个 ID | 退款记录（包含所有状态） | 必要 |
| `get_product_info(product_ids)` | 每次最多 100 个 ID | 商品目录信息 | 冗余 |
| `get_product_reviews(product_id, limit=20)` | | 商品评价 | 冗余 |
| `get_warehouse_stock(warehouse)` | | 库存 | 冗余 |
| `get_sales_summary(year, month)` | | 全平台月 GMV | 冗余，干扰项 |

训练 Harness 如果以 `(tool_name, arguments)` 的形式发起调用，可以用通用分发入口 `env.call(name, **kwargs)`；`ShopEnv.tool_names()` 返回所有可用工具名。

数据库以只读模式打开（`mode=ro`），智能体无法修改数据。

## 5. 典型执行路径与数据依赖

```
get_membership_tiers ──> VIP 等级代码 [T3, T4] ──────────┐
get_region_cities("华东") ──> 城市列表 ───────────────────┤
                                                          v
                                list_customers(cities, tier_codes) ──> customer_ids
                                                          v
        get_orders(customer_ids, 2026-07-01, 2026-09-30, status=completed)
        按 100 个 ID 分批、按页翻页 ──> order_ids、order_count
                                     │
                    ┌────────────────┴────────────────┐
                    v                                 v
          get_order_items(order_ids)         get_refunds(order_ids)
          Σ qty × unit_price × (1-disc)      Σ amount where status=approved
                    └────────────────┬────────────────┘
                                     v
                     net_sales = 商品金额 - 已批准退款
```

参考路径共 6 类 API 调用，每一步的输入都依赖前一步的输出：

1. 等级代码和城市列表来自前两次调用，不能凭常识猜
2. 有了这两样，才能查出客户 ID
3. 有了客户 ID，才能查订单 ID
4. 有了订单 ID，才能查明细和退款

最终答案需要跨 API 关联，再做二次计算（加权求和、按状态过滤、相减），任何一个 API 的返回都不能直接作为答案。

样例任务（华东、2026 年第 3 季度）的真值为 `net_sales = 357180.81`，`order_count = 45`（具体数值以 demo 输出为准）。

## 6. 奖励计算逻辑（`verifier/reward.py`）

验证器只看最终答案，不检查 API 调用的顺序、次数和形式。中间步骤出错，会体现为最终数值的偏差，从而反映在奖励里。

1. **解析任务**：用正则从自然语言任务中提取年份、季度和地区。任务无法解析时，奖励为 0
2. **计算真值**：用一条可信的参考 SQL 直接查询数据库（结果带缓存）
3. **解析答案**：支持 dict、JSON 字符串、自由文本里的 JSON 或 `<answer>` 标签。格式非法、缺少字段、出现 NaN/Inf 或布尔值时，奖励为 0
4. **分项打分**（阈值在 `config.py` 里统一管理）：
   - `net_sales`：相对误差 `e = |pred - gt| / max(|gt|, 1)`
     - `e ≤ 0.1%` 时得 1
     - `e ≥ 2%` 时得 0
     - 两者之间线性递减
   - `order_count`：完全一致得 1；否则得 `max(0, 1 - |diff| / (0.2 × gt))`
5. **加权汇总**：`reward = 0.8 × s_sales + 0.2 × s_count`，再截断到 [0, 1]

这样设计的原因：

- 净销售额是核心目标，所以权重最高
- 订单数提供部分奖励，帮助区分"筛选条件全对、只是金额算错"和"筛选条件就错了"
- 2% 的零分阈值足够严格，像"多扣了未批准的退款"这类细微错误也会被明显惩罚

### 调用方式（训练集成）

```python
from verifier import compute_reward, evaluate

reward = compute_reward(task_prompt, final_answer)   # float in [0, 1]
report = evaluate(task_prompt, final_answer)         # 带真值、分项得分、错误原因，便于调试
```

一个完整 episode 的示意：

```python
from rlvr_env.api import ShopEnv
from rlvr_env.tasks import make_prompt
from verifier import compute_reward

env = ShopEnv()
prompt = make_prompt(2026, 3, "华东")
# ... 智能体循环调用：result = env.call(tool_name, **arguments)
reward = compute_reward(prompt, agent_final_answer)
env.reset()
```

## 7. 调用样例输出（`examples/run_demo.py`）

| 场景 | 奖励 |
|---|---|
| 正确答案（参考路径） | 1.0000 |
| 正确答案，包在自然语言文本里 | 1.0000 |
| 错误：按 `level>=3` 判定 VIP（混入内部员工） | 0.0000 |
| 错误：扣除了所有状态的退款 | 0.2000（订单数正确，只拿到这部分分） |
| 错误：把"已发货"当成"已完成" | 0.0000 |
| 错误：走 `get_sales_summary` 捷径 | 0.0000 |
| 非法：答案不是 JSON | 0.0000 |
| 非法：缺少字段 | 0.0000 |

另外两个样例任务（华北 2026 Q1、华南 2026 Q4）用参考路径作答，奖励都是 1.0。无法解析的任务，奖励为 0。

## 8. 适用的 RLVR 训练场景

- **多步工具调用（tool-use agent）**：训练智能体规划调用链，并把上一步的输出传给下一步作为参数
- **业务语义落地**：训练智能体把"VIP""已完成""净销售额"这类业务术语，映射成具体的字段和过滤条件，同时避开看起来合理的捷径
- **长输出与分页处理**：ID 每批最多 100 个、需要翻页，训练智能体完整处理批量数据，不漏数据
- **可扩展的任务集**：年份、季度、地区组合起来可以批量生成任务；改 `config.py` 里的随机种子或数据规模，就能得到新的数据分布，减少记忆真值的风险

## 9. 已知限制

- 场景只有一种任务模板，可以继续扩展，比如按品类统计、复购率等
- 数据是合成数据，分布比较简单
- 验证器只做数值判定，不评价推理过程，这本身也是题目要求
