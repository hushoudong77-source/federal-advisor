# 全池21标分析数据覆盖矩阵 V1.0

> 签发：2026-05-13 01:25 | 状态：🟢 激活
> 用途：每次/分析或/扫描前自动参照，确保「先取数后分析」，消除「没数据」模糊地带

---

## 取数流程总纲

```
每次分析启动
  ├── Step 0: 读取本矩阵 → 确认目标标的数据项清单
  ├── Step 1: P1记忆 → memory_get当日+前日 → 守东已投喂数据
  ├── Step 2: P2 Tushare → 日线/EMA/ATR/SHIBOR/us_tycr
  ├── Step 3: P3 妙想 → A股资金流向/涨跌比/CRB/布伦特  
  ├── Step 4: P4 web_search → USDCNY/DXY/VIX（P2/P3不覆盖的锚点）
  └── Step 5: P0向守东确认 → 仅Step1-4全部失败时
```

**核心原则**：Step1-4能拿到的数据，严禁跳至Step5问守东。

---

## 一、美股板块（9标）— Tushare us_daily 全覆盖

| 标的 | 类型 | 数据项 | 来源 | 自动？ |
|:---|:---|:---|:---|:---:|
| QQQ | 进攻候选 | EMA30/50/150, ATR(14), H20, V20 | P2 Tushare `us_daily` | ✅ |
| IVV | 进攻候选 | 同上 | P2 Tushare `us_daily` | ✅ |
| BBJP | 反击候选 | EMA + ATR + 锚线MA40买入区间 | P2 Tushare `us_daily` | ✅ |
| MUFG | 反击候选 | EMA + ATR + 锚线MA40买入区间 | P2 Tushare `us_daily` | ✅ |
| EWY | 反击候选 | EMA + ATR + 锚线MA40买入区间 | P2 Tushare `us_daily` | ✅ |
| VNM | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `us_daily` | ✅ |
| FLIN | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `us_daily` | ✅ |
| SMIN | 观察期 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `us_daily` | ✅ |
| IAU | 豁免 | 现价/EMA（持仓管理） | P2 Tushare `us_daily` | ✅ |

**美股ETF特殊规则**：
- Tushare返回前复权价 → 绝对价格以P0守东截图为真
- 相对指标（涨跌幅/EMA方向/乖离率/ATR/H20）以Tushare为准
- C4当日成交量：Tushare天然滞后1个交易日 → **必须标注缺口，不可假装数据完整**

---

## 二、A股板块（9标）— Tushare fund_daily 全覆盖

| 标的 | 类型 | 数据项 | 来源 | 自动？ |
|:---|:---|:---|:---|:---:|
| 510300 | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `fund_daily` | ✅ |
| 510500 | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `fund_daily` | ✅ |
| 159915 | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `fund_daily` | ✅ |
| 588000 | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `fund_daily` | ✅ |
| 513180 | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `fund_daily` | ✅ |
| 513770 | 反击候选 | EMA + ATR + 锚线MA60买入区间 | P2 Tushare `fund_daily` | ✅ |
| 513910 | 反击候选 | EMA + ATR + C1-C4进攻判定 | P2 Tushare `fund_daily` | ✅ |
| 159545 | 反击候选 | EMA + ATR + 锚线MA40买入区间 | P2 Tushare `fund_daily` | ✅ |
| 159302 | 反击候选 | EMA + ATR + 锚线MA20买入区间 | P2 Tushare `fund_daily` | ✅ |
| 518880 | 豁免 | 现价/EMA（持仓管理） | P2 Tushare `fund_daily` | ✅ |

**A股ETF特殊规则**：
- Tushare fund_daily返回真实价格（非前复权）→ 可直接用于绝对价格
- A股T+1交割 → C4当日成交量Tushare通常当日可获取（与美股不同）
- 资金流向（主力净额/DDX/DDY）→ 降级至P3妙想mx-data

---

## 三、宏观锚点全覆盖

| 锚点 | 数据项 | 最佳来源 | 自动？ | 备注 |
|:---|:---|:---|:---:|:---|
| **SHIBOR 3M** | 银行间拆借利率 | P2 Tushare `pro.shibor()` | ✅ | 严禁web_search |
| **US10Y** | 10年期美债收益率 | P2 Tushare `pro.us_tycr()` | ✅ | 优先P2，盘中P0补充 |
| **US20Y** | 20年期美债收益率 | P2 Tushare `pro.us_tycr()` | ✅ | 同上 |
| **USDCNY** | 人民币中间价 | P4 web_search（新浪/东财/金投网） | ✅ | **四步获取，严禁直接问** |
| **USDCNH** | 离岸人民币 | P4 web_search | ✅ | 同上 |
| **DXY** | 美元指数 | P4 web_search / P0守东投喂 | ⚠️ | P2/P3不覆盖 |
| **VIX** | 恐慌指数 | P4 web_search / P0守东投喂 | ⚠️ | P2/P3不覆盖 |
| **CRB** | 商品指数 | P3 妙想 mx-macro-data | ✅ | |
| **布伦特** | 原油 | P3 妙想 mx-macro-data | ✅ | |
| **800005** | A股平均股价 | P0守东投喂 / P4公开行情 | ⚠️ | 优先P0 |
| **000922** | 中证红利 | P0守东投喂 / P4公开行情 | ⚠️ | 优先P0 |
| **涨跌比** | A股情绪指标 | P3 妙想 mx-data | ✅ | |

### USDCNY 四步强制流程（禁止跳步）

```
Step 1: P1记忆 → memory_get 当日/前日 → 守东投喂的USDCNY
Step 2: P4 web_search → "美元兑人民币 USDCNY 中间价 YYYY年M月D日"
         → 新浪财经/东方财富/金投网/证券之星
Step 3: 标注来源（P1记忆 vs P4搜索），P4数据标注「P4获取，P0优先」
Step 4: 仅Step1+Step2均失败 → 向守东确认
```

- **中间价**（央行9:15发布）：用于B账户CNY换算
- **在岸收盘**（16:30）：用于市场锚点判断
- **盘中实时变动**：仍需守东P0供弹，P0优先权不变

---

## 四、唯一无法自动获取的数据

| 数据项 | 原因 | 处理方式 |
|:---|:---|:---|
| C4当日成交量（美股ETF） | Tushare数据滞后1个交易日 | 标注「Tushare最新: YYYY-MM-DD，当日成交量待确认」 |
| 盘中实时锚点（DXY/VIX） | 无实时API | 使用P4最近收盘，标注「P4估算，盘中P0优先」 |
| 800005/000922精确值 | 无直接API | P3妙想/P4公开行情估算，标注「P4估算，P0优先」 |
| 守东持仓成本/股数 | P0专属 | 向守东确认（合规） |
| TD序列/DK点/五档盘口 | 无API | 仅守东截图可获取 |

---

## 五、取数违规熔断清单

以下任一行为触发熔断，立即中止并记录：

1. ❌ 输出「请提供USDCNY」→ P4 web_search可获取
2. ❌ 输出「请提供SHIBOR」→ P2 Tushare可获取
3. ❌ 输出「请提供US10Y」→ P2 Tushare可获取
4. ❌ 输出「请提供EMA/ATR数据」→ P2 Tushare可获取
5. ❌ 用P4 web_search获取SHIBOR → 跳过P2 Tushare
6. ❌ 未标注C4成交量缺口 → 假装数据完整
7. ❌ 凭记忆输出标的代码未核对全池清单 → 直觉拦截

---

## 六、自检清单（每次分析启动前）

```
□ P1记忆已读取？（memory_get 当日+前日）
□ P2 Tushare已调用？（标的日线 + SHIBOR + US10Y）
  ├── □ us_daily() — 全池美股标的 → 150EMA/50EMA/MACD自算
  ├── □ fund_daily() — 全池A股ETF → 同上
  ├── □ shibor() — SHIBOR各期限
  └── □ us_tycr() — US10Y/US20Y
□ P3 妙想已调用？（A股资金流向/涨跌比/CRB/布伦特 按需）
□ P4 web_search已调用？（USDCNY四步流程 / DXY/VIX补充）
□ 🔴 扫描专属：报表中所有乖离率/MACD是否来自Tushare实时计算？是否存在「—」未说明？
□ C4成交量缺口已标注？
□ EMA基值日期已标注？
□ 全池21标清单已核对？（直觉拦截协议）
□ 仅在Step1-4全部失败后才转向P0确认？
```

---

> 本矩阵为取数执行硬规格。每次分析前读取本页 → 逐项check → 全量数据就绪后再启动分析。消除「没数据」模糊地带。
