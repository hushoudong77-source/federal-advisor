## [LRN-20260525-001] best_practice

**Logged**: 2026-05-25T13:20:00+08:00
**Priority**: medium
**Status**: pending
**Area**: config

### Summary
self-improving-agent skill installed — auto-capture corrections, errors, and feature requests to .learnings/

### Details
Installed via `npx clawhub install self-improving-agent` into skills/self-improving-agent/.
Initialized .learnings/ directory with LEARNINGS.md, ERRORS.md, FEATURE_REQUESTS.md.
When user corrects me, when commands fail, or when better approaches are discovered — log immediately.

### Metadata
- Source: installation
- Related Files: .learnings/LEARNINGS.md, .learnings/ERRORS.md, .learnings/FEATURE_REQUESTS.md
- Tags: self-improvement, learning-system

---



## [LRN-20260529-001] correction — 取数优先级硬化：禁用P5级均线推断

**Logged**: 2026-05-29T15:30:00+08:00
**Priority**: critical
**Status**: pending
**Area**: config

### Summary
510500 MA120取值错误——用了60分钟K线数据（P5级AI推断）而非Tushare日线API（P2级真源），导致MA120误差达+5.6%（8.553 vs 8.099）。根因：取数优先级执行缺陷，P5级推断绕过了P2级API。

### Details
- 错误：60分钟线MA120=8.553（P5 AI推断）
- 正确：Tushare fund_daily MA120=8.099（P2 API真源）
- 偏差：+0.454 (+5.6%)
- 根因：AGENT.md模块零规定了取数优先级（P0>P1>P2>P3>P4>P5），但未明确规定「P5 AI推断值不得用于均线/技术指标等可API获取的数据」，导致P5级推断绕过了P2 Tushare优先取数流程
- 守东指令：除用户投喂（P0/P1）外，高等级优先使用Tushare API取值

### Suggested Action
在AGENT.md模块零取数强制流程中新增一条硬规则：
**所有技术指标（均线/乖离率/MACD/ATR等）必须来自P2 Tushare API实算或P0用户投喂，严禁使用AI推断值（P5）——无论该推断基于什么时间周期或数据源。Tushare数据更新滞后（A股当日18:00后入库/美股次日6:00后）仅在输出时标注滞后日期，不得用P5填充。**

### Metadata
- Source: user_feedback
- Related Files: AGENT.md
- Tags: data-priority, correction, tushare, ma-calculation
- See Also: LRN-20260525-001
- Pattern-Key: data.priority.p5-override
- Recurrence-Count: 1
- First-Seen: 2026-05-29
- Last-Seen: 2026-05-29

---

## [LRN-20260602-001] correction — C4/H20必须P0覆写，严禁用前复权价

**Logged**: 2026-06-02T12:55:00+08:00
**Priority**: critical
**Status**: resolved (promoted to AGENT.md)
**Area**: config

### Summary
C4=H20×0.98 不能用Tushare前复权价计算——前复权H20与真实H20偏差可达-11.7%，直接导致C4判定翻转。

### Details
2026-06-02 12:54 分析588000时，用Tushare fund_daily前复权价取H20=1.765→C4=1.7297→判定「已触发」。实际P0真实H20=1.998→C4=1.9580→判定「未触发」。两条结论完全相反。守东训诫：「这是非常严重的」。

### Root Cause
规则K Step K4将C4归入「技术指标，继续用Tushare计算值」。但C4=H20×0.98依赖价格绝对值，前复权偏差直接导致判定翻转。Step K4归类错误。

### Fix Applied
AGENT.md 规则K追加 Step K4.1：C4/H20强制P0覆写检查。输出C4判定前必须扫描当日记忆提取H20，命中P0则覆写，未命中则标注来源。连续2次违规→C4强制P0模式。

### Metadata
- Source: user_correction
- Related Files: AGENT.md, memory/2026-06-02.md
- Tags: C4, H20, 前复权, 规则K漏洞
- Pattern-Key: hardening.C4_H20_覆写
- Recurrence-Count: 1
- First-Seen: 2026-06-02
- Last-Seen: 2026-06-02

---

## [LRN-20260602-002] best_practice — RPS排名焊入/开火模板

**Logged**: 2026-06-02T17:59:00+08:00
**Priority**: medium
**Status**: pending
**Area**: config

### Summary
ETF动量轮动策略（RPS排名）与法典框架对撞后，决定将RPS(20)和RPS(60)排名作为辅助排序维度整合进 `/开火` 指令的输出模板，不形成独立决策信号。

### Details
- 核心原则：RPS排名做候选标的内部分级，不覆盖ATR止损/冷却期/分层管理
- 反击买入区：追加RPS(20)排名 — 动量耗尽反而是好事，捡便宜货
- 进攻买入区：追加RPS(20)+RPS(60)排名 — 同条件标的按RPS排序
- 固定层/黄金/剥夺：RPS列标记「N/A」
- 穿透审计发现：EWY断层领先但不可操作（反击资格已剥夺）、588000 RPS(60) vs RPS(20)差异揭示反击逻辑、513910排#16是好事（动量耗尽=反击买入窗口）
- 知识库已入库：`knowledge/concepts/etf-momentum-rps-v1.md`

### Metadata
- Source: user_feedback
- Related Files: knowledge/concepts/etf-momentum-rps-v1.md, knowledge/index.md
- Tags: rps, momentum, /开火, 模板升级
- Pattern-Key: hardening.rps-integration
- Recurrence-Count: 1
- First-Seen: 2026-06-02
- Last-Seen: 2026-06-02

---
