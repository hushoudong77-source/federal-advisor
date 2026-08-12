### 🔴 模块十四.五：大师对撞独立前置数据新鲜度校验协议（2026-06-27 焊入）

**核心原则**：`/大师对撞` 是单标深度分析指令，不需要跑完整执行链（全池拉取+持仓对账+P0覆写全池对单标是冗余），但**必须确保所有技术指标基于Tushare最新日线实时计算，严禁使用任何缓存数据**。

**根因**：2026-06-27 BOTZ大师对撞事故——EMA50/EMA150/MACD/RSI/ATR/ADX/KDJ/H20全部来自过期缓存，EMA50偏差−12.8%，MACD BAR符号翻转（金→死），导致方向性误判。

**前置强制三步校验**（不可跳过）：

```
/大师对撞 [标的代码] 触发
    │
    ├── Step 1: 拉取Tushare最新日线
    │   ├── 美股: pro.us_daily(ts_code='标的', start_date='YYYY-MM-DD', end_date='YYYY-MM-DD')
    │   ├── A股ETF: pro.fund_daily(ts_code='标的.SH/.SZ', ...)
    │   ├── 最少行数: ≥280条（覆盖MA250初始化+EMA150+ATR14+H20）
    │   └── 行数不足 → 扩展start_date重拉，直到满足
    │
    ├── Step 2: 基于最新日线自算全部技术指标
    │   ├── EMA50/EMA150/EMA30 — pandas ewm(span=N).mean()
    │   ├── MA5/MA20/MA40/MA60/MA120/MA150/MA250 — pandas rolling(N).mean()（七线全覆盖）
    │   ├── ATR14 — 14日真实波幅均值
    │   ├── MACD — EMA12−EMA26=DIFF, DEA=EMA9(DIFF), BAR=2×(DIFF−DEA)
    │   ├── RSI14 — 14日RSI
    │   ├── ADX14 — 14日ADX（含+DI/−DI）
    │   ├── KDJ — 9日周期RSV→K→D→J
    │   ├── OBV — 累计量：涨+量、跌−量
    │   ├── H20 — 20日内最高收盘价
    │   └── VOL_MA20 — 20日均量
    │
    └── Step 3: 标注新鲜度指纹
        ├── latest_date = Tushare返回的最新日线日期
        ├── 逐指标标注计算窗口: 「值 [窗口: YYYY-MM-DD..YYYY-MM-DD, N条]」
        ├── 所有指标的计算窗口结束日期 = latest_date → ✅ 通过
        ├── 任一指标结束日期 < latest_date → ❌ 过期！强制重算
        └── 无法追溯到Tushare日线的指标 → ❌ 来源不明！禁止输出
```

**新鲜度指纹输出格式**（大师对撞报告正文前强制输出）：

```
🔒 大师对撞数据新鲜度校验：
├── 标的: [代码] | 数据源: Tushare [us_daily/fund_daily]
├── latest_date: YYYY-MM-DD | 拉取行数: N条
├── EMA50=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 50条] ✅
├── EMA150=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 150条] ✅
├── MA5=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 5条] ✅
├── MA20=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 20条] ✅
├── MA40=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 40条] ✅
├── MA60=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 60条] ✅
├── MA120=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 120条] ✅
├── MA150=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 150条] ✅
├── MA250=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 250条] ✅
├── ATR14=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 14条] ✅
├── MACD: DIFF=[值]/DEA=[值]/BAR=[值] ✅
├── RSI14=[值] ✅
├── ADX14=[值] ✅
├── KDJ: K=[值]/D=[值]/J=[值] ✅
├── H20=[值] [窗口: YYYY-MM-DD..YYYY-MM-DD, 20条] ✅
└── 全指标新鲜度: 通过 / ❌ [列出过期指标]
```

**与规则N执行链的关系**：
- 规则N执行链适用于全池多标指令（/扫描 /开火 /进攻 /反击 等）
- 大师对撞独立前置协议适用于单标深度分析（/大师对撞）
- 两者不互斥——`/大师对撞` 触发时先跑独立前置三步，再按大师对撞模板输出
- 独立前置三步 = 规则N执行链中 Step 1(规则G拉取)+Step 4(规则M.1新鲜度) 的单标精简版
- 不包含 Step 0.5(持仓对账) / Step 3(P0覆写全池) / Step 5(零请提供) — 单标场景冗余

**自检熔断**：
- 触发：大师对撞输出中任何技术指标无法追溯到Tushare最新日线 → **指标过期违规，立即中止，补拉重算**
- 触发：大师对撞输出前未出现「🔒 大师对撞数据新鲜度校验」段落 → **前置校验跳过违规**
- 触发：新鲜度指纹显示任一指标结束日期 < latest_date → **缓存复用违规**
- 触发：指标未标注计算窗口日期范围 → **来源不明违规**
- 触发：同一会话中连续2次大师对撞跳过前置校验 → 自动激活「大师对撞强制Tushare模式」，该会话剩余所有大师对撞强制先拉Tushare再输出

---

