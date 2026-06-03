# 联邦情报网 V2.0 — 四层情报矩阵

**签发日期**: 2026-05-07  
**最后修订**: 2026-05-15（V2.6：删除L2 0DTE负伽马漩涡监测——数据真空区+杀鸡用牛刀+与US10Y双重征税，守东裁决移除）  
**签发背景**: 12 个妙想 Claw Skill 批量安装完成，补齐地缘事件/宏观数据/行业比较三大情报短板  
**状态**: 即时启用，嵌入所有 `/扫描` `/分析` 及日常审计流程

---

## 一、旧版情报网的三个断裂点

| 断裂点 | 症状 | 后果 |
|:---|:---|:---|
| 地缘/战争事件 | 无系统化信源，依赖统帅口头转述 | 霍尔木兹事件传导链仅凭经验推断 |
| 宏观数据发布 | 依赖人工投喂 + web_search 盲搜 | 数据滞后、信源不可靠 |
| 事件→标的传导 | 凭经验推断，无底层数据验证 | 无法量化冲突对具体持仓的影响 |

---

## 二、四层情报矩阵

| 层级 | 情报类型 | 激活 Skill | 数据覆盖 | 频率 |
|:---|:---|:---|:---|:---:|
| **L1 宏观重力场** | DXY/CRB/布伦特/US10Y/VIX | mx-macro-data（商品类） + 用户供弹（利率/汇率类） | ⚠️ 利率/汇率不覆盖 | 每日 |
| **L2 事件冲击波** | 地缘冲突、政策突变、经济数据发布、突发新闻 | mx-finance-search + mx-search + **cls_telegraph（财联社电报）** | ✅ 公告/研报/新闻/政策 + 实时电报 | 触发式 + 决策前强制 |
| **L3 市场情绪场** | A股热点、资金流向、涨跌比 | stock-market-hotspot-discovery + plugin-hot-trends-hub + plugin-gw1kuD | ✅ 全平台热点 | 每日 |
| **L4 标的深度** | 财报、研报、公告、可比分析 | mx-finance-data + stock-earnings-review + comparable-company-analysis + stock-diagnosis | ✅ 全市场深度 | 事件触发 |

### L2 补充：财联社电报（cls_telegraph）强制接入

**接入脚本**: `scripts/cls_telegraph.py`（基于 AKShare `stock_info_global_cls` 接口）

**强制触发节点**：
- 每次 `/分析` 指令启动时，自动拉取最近20条全部电报 + 10条重点电报
- 每次 `/扫描` 指令启动时，自动拉取最近15条全部电报
- 任何涉及「卖出/减仓/加仓」决策前，拉取对应标的的关键词过滤电报

**用法**：
```bash
python3 scripts/cls_telegraph.py --count 20          # 决策前拉取
python3 scripts/cls_telegraph.py --symbol 重点        # 只看重点
python3 scripts/cls_telegraph.py --filter "芯片|AI"   # 标的关联过滤
```

**数据角色**：财联社电报提供**分钟级实时突发新闻**，填补 mx-finance-search（东财数据库）可能存在的资讯滞后。两者互补——mx-finance-search 覆盖公告/研报/深度，财联社覆盖实时快讯。

## 三、mx-macro-data 硬覆盖边界（关键约束）

| 数据类别 | mx-macro-data | 替代方案 |
|:---|:---:|:---|
| 商品（CRB/布伦特/黄金/铜） | ✅ 直接取 | — |
| 利率（US10Y/SHIBOR/中国10Y） | ❌ 不覆盖 | 用户供弹 + web_search |
| 汇率（DXY/USDCNY） | ❌ 不覆盖 | 用户供弹 + web_search |
| 经济指标（CPI/GDP/非农） | ⚠️ 部分可用 | mx-finance-search 补充 |
| 中国宏观（M2/PMI/PPI） | ⚠️ 部分可用 | mx-finance-search 补充 |

**执行规则**: L1 中商品类自动取 mx-macro-data，利率/汇率类必须等待统帅供弹或通过 web_search 抓取。

---

## 四、事件响应 SOP（以美伊冲突为例）

```
触发条件: 地缘冲突升级 / 宏观数据超预期 / 政策突变

Step 0: cls_telegraph 拉取实时电报（强制前置）
        python3 scripts/cls_telegraph.py --count 30

Step 1: mx-finance-search 搜索事件最新进展
        "霍尔木兹海峡 航运 受阻 最新动态"

Step 2: mx-finance-search 搜索机构观点
        "布伦特原油 供应中断 投行 观点"

Step 3: mx-finance-data 查询受影响的标的底层持仓
        例: 513910 成分股中能源/航运相关权重

Step 4: mx-macro-data 查询相关商品价格
        "布伦特原油 最新价格"

Step 5: 联邦四线程对撞 → 量化传导链 → CEO 决策
```

---

## 五、每日情报采集清单（/扫描 自动触发）

| 序号 | 采集项 | Skill | 备注 |
|:---:|:---|:---|:---|
| 1 | CRB/布伦特/黄金 最新价格 | mx-macro-data | 商品类可自动取 |
| 2 | DXY/US10Y（宏观重力场） | 用户供弹 | mx-macro-data 不覆盖 |
| 3 | A股市场热点 | stock-market-hotspot-discovery | 自动 |
| 4 | 全网热点 | plugin-hot-trends-hub | 自动 |
| 5 | 财经早报 | plugin-gw1kuD | 自动 |
| 6 | 持仓标的相关公告/研报 | mx-finance-search | 触发式 |

---

## 六、与联邦四线程的嵌入关系

```
Sentinel-01 物理层
├── L1 宏观重力场（DXY/CRB/布伦特/US10Y/VIX）
├── L4 标的价格/财务数据（mx-finance-data）
└── 原有物理锚点（均线/ATR/RSI）

首席审计官 证伪层
├── L2 事件冲击波（mx-finance-search 抓取反方证据）
├── L4 可比公司分析（comparable-company-analysis 交叉验证）
└── 原有黑帽审计逻辑

CEO 决策层
├── 综合 L1-L4 情报
├── 量化传导链（事件→标的）
└── 输出行动指令
```

---

## 七、已知局限

1. mx-macro-data 不覆盖利率/汇率 → DXY/US10Y 仍依赖统帅供弹
2. mx-finance-search 的资讯时效性取决于东财数据库更新频率
3. stock-market-hotspot-discovery 仅覆盖 A 股，美股热点需其他渠道
4. comparable-company-analysis 仅支持 A 股上市公司
