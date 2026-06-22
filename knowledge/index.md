# Knowledge Index

> 最后整理：2026-06-22 07:15 | 文件数：92 | V5.8.2r33.0 在线 | TD9全策略嵌入+确认条件硬化焊入

## 🔴 核心执行法典（唯一真源）

- [V5.8.2r25 全量合并版](analysis/v56/v57-merged.md) — ⚠️已冻结（真源严重滞后，禁止用于执行参考）。拆分版为唯一真源。2026-05-21签发。
- [V5.8.2r30 §0 固定层宪法](analysis/v56/v56-constitution.md) — VEA+VTI 永不离场。r30新增§0.6固定层建仓纪律（买入区间/VIX熔断/冷却期/宏观事件静默期）。2026-06-10。
- [V5.8.2r31.6 §2 路由判断](analysis/v56/v56-routing.md) — 全池19标路由逻辑。r31.6自审P0修复（属地清单+800005替换）。2026-06-22签发。
- [V5.8.2r30 §3.1 进攻策略](analysis/v56/v56-spearhead.md) — Spearhead Protocol。r30新增C3.1大型IPO抽血事件（日本≥500亿日元/全球≥$300亿/A股≥300亿元）。2026-06-10签发。
- [V5.8.2r24 §3.2 反击策略](analysis/v56/v56-counterpunch.md) — Counterpunch Protocol。⭐r24新增§3.2.4反击系统物理死亡判定≥50笔。r23双区间+SMIN剥夺+暂停降仓+48h冷却期保留。2026-05-21签发。
- [V5.8.2r29 §1+§4+§5](analysis/v56/v56-macros.md) — 数据输入+波动率状态机+执行闭环。r29新增§4.7宏观事件日历前置检查（四层宏观防御体系全景）。2026-06-06签发。
- [V5.8.2r33.0 开火档案](fire-archive-v582.md) — 执行级快速参考。r33.0新增§九独立动量跟随策略参数矩阵（FLIN/SMIN/EWY V1.1动态回撤止盈）。2026-06-22签发。
- [金盾总纲 V1.4](concepts/gold-shield-protocol-v1.md) — IAU/518880黄金专属操作协议，七级卖点体系。V1.4三段划分回测校准：S4阈值升至3.5%，S6=3.0×/C3=1.2×/C4维持，2023年后C1-C4入场信号系统性失效。独立于通用法典。2026-05-23签发。
- [金盾战术前置方案](concepts/gold-shield-tactical-vanguard-v1.md) — ⭐2026-06-16焊入AGENT.md。金盾正统四条件的战术级前置补充。C1双顺风+MACD金叉+FOMC落地→三分之一仓位先行入场。剩余⅔等正统四条件全绿。仅适用于宏观拐点过渡窗口，非体系永久降级。
- [宏观危机状态机 V1.0](analysis/macro-crisis-state-machine-v1.md) — ⭐2026-06-03焊入AGENT.md模块十二。§4.4 VIX四档阈值（NORMAL≤20/ALERT 20-35/CRISIS 35-50/MELTDOWN>50）+ §6三阶段框架（崩盘确认期→政策干预期→复苏早期）。与US10Y形成双熔断互补，覆盖2020年3月式流动性危机（US10Y低但VIX飙升）。全池17标逐标三阶段处置矩阵。基于2000/2008/2020三次危机历史回测。
- [V5.6 审计合并版 V2.0 [已归档]](analysis/v56/v56-audit-merged.md) — 第四轮KIMI黑帽审计。2026-05-11。

## 📐 策略基础设施

- [参数不确定性下的动态投资组合选择](concepts/parameter-uncertainty-dynamic-portfolio-v1.md) — 基于§3.3.6学术框架的实践对撞。Brennan(1998)/Xia(2001)/Cvitanić(2006)的序贯学习方法 = 回测参数置信度分数的理论地基。2026-05-25入库。
- [统计模型与多重检验](concepts/statistical-models-trading-v1.md) — §2 全书方法论地基。缩减技术(Ledoit-Wolf)=回测框架V1.2已用，多重检验(FDR 5%)=已采用，Black-Litterman=固定层权重优化(未实施，含触发条件)。2026-05-25入库。
- [已实现波动率(RV)](concepts/realized-volatility-v1.md) — §4.3 高频波动率估计。RV是积分波动率的无偏一致估计量，与ATR14互补：RV暴涨→预警，ATR14上升→确认。当前数据基础设施不支持高频RV，但概念已用于CANE波动率分析。2026-05-25入库。
- [最优执行Almgren-Chriss框架](concepts/optimal-execution-almgren-chriss-v1.md) — §6.1-6.3。双曲正弦最优拆单策略。CANE $25K(0.25-0.5%日均量)<1%阈值→一把梭。各量级执行建议表。2026-05-25入库。
- [LOB与做市模型](concepts/order-book-hft-v1.md) — §5+§7。LOB五层结构、Hawkes过程(订单聚集效应→低流动性标的跳空解释)、Avellaneda-Stoikov做市模型(时间依赖逻辑→CANE分批时序安排)。联邦适用度整体低。2026-05-25入库。
- [Black-Litterman与联邦融合潜力](concepts/black-litterman-federal-v1.md) — §2.4.2。BL解决主观观点量化输入问题。固定层VEA/VTI权重优化的理论框架，当前不实施(固定层哲学矛盾+30%体量太小)，触发条件已定义。2026-05-25入库。
- [回测框架重建方案 V1.2 冻结执行版](analysis/backtest-framework-rebuild-plan-v1.2-final.md) — 四状态六级优先级状态机 / Ledoit-Wolf自适应+兜底 / FDR 5% / 三Regime制度断裂标记。全部硬规格冻结，可直接编码。2026-05-09冻结。
- [P1 全池回测报告 V1.3](analysis/p1-full-backtest-v1.3.md) — 19标全量回测绩效矩阵，六大核心发现。2026-05-07签发。
- [L1 买入区间命中率回测 V1.0](analysis/l1-backtest-2026-05-09-review.md) — 方法、结果与矛盾，提交外部专家审查的技术摘要。2026-05-09。
- [L1 买入区间命中率回测 V1.1](analysis/l1-backtest-2026-05-17.md) — 周度执行回测，V5.8.2r14参数体系，SMIN参数过宽/513910最优/EWY反弹率最高。2026-05-17。
- [反击策略逐标参数回测报告 2026-05-23](analysis/counterpunch-parameter-backtest-2026-05-23.md) — 法典SOP三段回测，13标18组参数全量对比。四重死亡螺旋诊断：伪最优=噪音。冻结裁决：维持全部参数不变。四道纪律红线写入宪法§5.6.4。2026-05-23签发。
- [反击策略参数敏感性走廊测试报告 2026-05-23](analysis/counterpunch-corridor-test-2026-05-23.md) — 全池13标走廊测试（MA±10 × k±0.5，9组/标）。裁决：IAU唯一鲁棒；EWY/SMIN/510500全区间负Sharpe否决；EWY反击资格剥夺已执行；510500标记待独立审计。2026-05-23签发。
- [决策体系定期回测 SOP V1.0](concepts/backtest-sop-v1.md) — 三层定期回测框架 + 触发式回测。2026-05-07签发。

## 🧠 核心思维框架

- [铁三角思维操作系统 V20.30.1](concepts/triangular-thinking-system.md) — 联邦投顾底层思维框架（认知美德 + 逻辑审计 + 平行思维）
- [数字资产审计官协议 V14.0](concepts/digital-audit-protocol-v14.md) — 确定性至上、数据对撞、执行熔断
- [全量数据审计协议 V1.0](concepts/full-data-audit-protocol.md) — 多标的数据分析强制性全景扫描协议
- [联邦学习方法论 V1.0](concepts/federal-learning-methodology-v1.md) — 系统化学习框架
- [学习模板库 V1.0](concepts/learning-templates-v1.md) — 7个核心学习模板

## 🌐 宏观重力场

- [联邦情报网 V2.5 — 四层情报矩阵](concepts/intelligence-grid-v2.md) — L1宏观重力场/L2事件冲击波(含0DTE负伽马漩涡)/L3市场情绪场/L4标的深度
- [中国区压强锚点体系 V3.0 [三锚精简确权]](concepts/china-anchor-system-v1.md) — ⭐三锚精简：DR007+债市杠杆率分位+USDCNY/USDCNH。800005/000922/AU9999/SHIBOR 3M/央行表态/上证沪深300已确权剔除，零信息损失。对撞矩阵8→4条。2026-05-23审计通过。真源在AGENT.md模块八。
- [A股涨跌比情绪指标 V1.0](concepts/advance-decline-ratio-v1.md) — 7级情绪分级，狂热线80%
- [全量标的映射关系网络 V1.1](concepts/asset-mapping-network-v1.md) — 60标三阶映射体系，19核心池映射树

- [趋势突破交易系统 V1.0](concepts/trend-breakout-trading-system-v1.md) — 守东口述选股/开仓/持股/离场全链路规则，联邦审计量化硬化。道氏趋势+压力线突破+放量确认+角度分治止损。与法典并行独立系统。2026-06-04入库。

## ⚔️ 大师方法论

- [守东量价交易系统 V1.0](concepts/shou-dong-two-kline-system-v1.md) — 删光所有指标，只剩两条K线：上车K线（缩量阴线→放量阳线站回）和下⻋K线（放量跌破趋势线）。核心逻辑：盈亏比优先于胜率，亏小钱赚大钱。2026-05-27入库。
- [ETF动量轮动策略 — RPS排名 vs 法典对撞](concepts/etf-momentum-rps-v1.md) — 84% ETF老油条最终只用一个动量排名信号的访谈结论，与法典三层均线+ATR止损+分层管理的对撞审计。确认共识与分歧，提出C3+RPS组合方案。V2.0追加实盘验证：全池18标RPS排名表+四个穿透审计发现+RPS焊入/开火模板规则。2026-06-02入库/实盘验证。
- [RPS + RSI 强势股回调框架](concepts/rps-rsi-strong-stock-pullback-v1.md) — 欧奈尔体系：RPS高位选强 + RSI低值择时，叠加板块共振/跌幅控制/缩量确认三过滤。联邦审计：逻辑自洽，与进攻策略互补，但RPS数据基础设施不支持实时计算，当前不焊入法典，作为人工辅助过滤层。2026-06-21入库。
- [FLIN/SMIN 动量跟随策略 V1.1](concepts/flin-smin-momentum-follow-v1.md) — ⭐2026-06-22焊入→同日V1.1动态回撤止盈。MACD金叉+价<MA20入场→止损2×ATR/两阶段退出（浮盈<1.5ATR→MA60止盈/浮盈≥1.5ATR→1.5ATR回撤止盈）。全仓进出不分批。FLIN V1.1 23笔/Sharpe 0.381/胜率60.9%，SMIN V1.1 34笔/Sharpe 0.163/胜率52.9%。均线过滤全面否决。

- [达利奥决策方法论](concepts/principles-dalio-methodology.md) — 五步进化循环、创意择优、圣杯配置
- [大师战术精华](concepts/trading-masters-tactics.md) — 全天候实战操盘知识库
- [CAN SLIM 买卖交易系统](concepts/can-slim-buy-sell-protocol.md)
- [SEPA 策略与 VCP 审计协议](concepts/sepa-vcp-audit-protocol.md)
- [阶段分析与均线审计协议](concepts/weinstein-stage-analysis-protocol.md)
- [期望值与头寸审计协议](concepts/expectancy-position-sizing-protocol.md)
- [交易心理审计协议](concepts/trading-psychology-protocol.md)
- [周期胜率审计协议](concepts/cycle-probability-audit-protocol.md)
- [系统开发与概率审计协议](concepts/system-development-probability-audit-protocol.md)
- [全市场维度审计协议](concepts/full-market-dimension-audit-protocol.md)
- [宏观周期审计协议](concepts/macro-cycle-audit-protocol.md)
- [宏观周期与利率对账协议](concepts/macro-cycle-interest-rate-protocol.md)
- [股市技术分析操作手册](concepts/technical-analysis-operations-handbook.md)
- [全球资产交易系统 V13.1](concepts/global-asset-trading-system-v13.md)
- [熔断法典 6.0](concepts/circuit-breaker-codex-v6.md)

- [金盾总纲 V1.2 [已归档]](concepts/gold-shield-protocol-v1.md) — ~~V1.4已取代，详见上方V1.4条目~~

- [政策信号市场证伪协议 V1.0](concepts/policy-signal-market-validation-v1.md) — ⭐2026-06-17焊入AGENT.md模块八。所有政策表态/官员讲话/论坛宣言需经市场真金白银确认后才可纳入决策。三条件证伪（反向波动/无视缩量/脉冲回吐）。与模块七外部指令隔离协议互补。2026-06-17入库。

## 🔧 专项协议与模块

- [CANE (Teucrium Sugar Fund) 跟踪协议 V1.0](concepts/cane-tracking-protocol-v1.md) — 糖商品ETP跟踪协议，不入全池21标，P4取数，/扫描末尾附加行情模块。2026-05-24签发。

- [废墟收割协议 V2.0](concepts/ruins-harvesting-protocol-v2.md) — ⭐M3完成：双参数体系固化（-2.50/-1.25），假废墟率14.4%达标，90笔全周期回测验证，四标的全量覆盖。2026-05-23签发。
- [废墟收割协议 V1.9r6 [已归档]](concepts/ruins-harvesting-protocol-v1.md) — V1.9r6 M2完成+Channel A分级上线（2026-05-21）：β标定回测通过（4港股ETF vs HSI 2018-2026），513180/513770激活β通道（准入：β>0.8∧corr>0.5∧尾部β>0.3），513910/159302永久禁用β通道退回纯跳空豁免。V1.9r5 Beta标定全量重写（KIMI十次黑帽审计裁决焊入）保留。
- [2026年厄尔尼诺→商品资产传导全链路 V1.0](concepts/el-nino-commodity-chain-2026-v1.md) — 国盛证券5/20报告+NOAA预测+历史13次厄尔尼诺复盘。覆盖白糖(6年周期见底)/棕榈油(滞后4Q)/橡胶(滞后5Q)/棉花(需求库存约束)/煤炭电力(高温传导链)。与CANE协议直接对账。2026-05-26入库。
- [产业事件驱动交易模块 V1.0](concepts/event-driven-trading-module-v1.md) — 三层漏斗的事件驱动交易体系
- [K线形态 + MACD 动能审计附录 V1.1](concepts/kline-macd-audit-appendix-v1.md) — 12种K线形态识别 + MACD动能审计 + 多维裁决协议
- [技术指标自主计算集成协议 V1.3](concepts/technical-indicators-integration-protocol-v1.md) — MACD/ATR/RSI/TD9全策略嵌入+确认条件硬化。V1.3新增低位9转/高位9转命名纠正、三确认条件AND（缩量<0.8+小实体<0.3×ATR）、五策略嵌入位置、calc_td9.py计算引擎。2026-06-22焊入。
- [黄金分析记忆关联协议 V2.0](concepts/gold-analysis-memory-protocol.md) — 五维对撞体系
- [妙想 Skill 使用指南 V1.0](concepts/mx-skills-usage-guide-v1.md) — 五大Skill实测覆盖度与限制
- [GEMINI V20.34.5 数据供弹协议](concepts/gemini-v20.34.5-data-supply-protocol.md)
- [GEMINI 进阶分析框架 V1.0](concepts/gemini-advanced-framework-v1.md)
- [GEMINI 双角色分析协议](concepts/gemini-dual-role-analysis.md)
- [角色切换协议 V20.31.6](concepts/role-switching-protocol-v20.31.6.md)
- [战时审计协议](concepts/wartime-audit-protocol.md)
- [日常审计协议](concepts/daily-audit-protocol.md)

## 📋 报告模板

- [全球战场全量扫描报告模板 V20.56.19](concepts/scan-report-template-v20.36.0.md) — 当前 `/扫描` 指令标准模板
- [开盘即时扫描模板 V1.0](concepts/market-open-scan-template.md) — 用户投喂开盘数据后自动触发，含国内压强锚点（SHIBOR 3M/800005/000922/涨跌比）四锚联动
- [标的分析报告模板 V20.34.7](concepts/analysis-report-template-v20.34.7.md) — GEMINI风格精简版
- [战场审计终极模板 V20.31.3](concepts/battlefield-audit-template-v20.31.3.md)
- [数据审计报告模板 V1.1](concepts/data-audit-report-template-v1.0.md)
- [大师对撞模板 V1.0](concepts/masters-collision-template-v1.0.md)
- [最终执行指令展示模板 V20.31.7](concepts/execution-instruction-template-v20.31.7.md)
- [微信入口执行模板 V20.32.2](concepts/wechat-execution-template-v20.32.2.md)
- [目标标的全景扫描审计模板 V20.31.4](concepts/target-scan-audit-template-v20.31.4.md)

## 📜 历史审计报告（按日期）

- [2026-05-06 法典 V20.54.0 回测校准报告](analysis/2026-05-06-codex-backtest-v20.54.0.md)
- [2026-05-02 五大宏观锚点技术指标供弹审计](analysis/2026-05-02-macro-anchor-indicators-dump.md)
- [2026-04-28 日元159.29汇率重力对撞](analysis/2026-04-28-jpy-159-collision.md)
- [2026-04-27 韩国EWY踏空复盘](analysis/2026-04-27-korea-ewy-step-loss-analysis.md)
- [2026-04-25 GEMINI 26轮深度对撞全量分析](analysis/2026-04-25-gemini-26-turn-collision-deep-analysis.md)
- [2026-04-25 B账户避险转移 vs 废墟收割逻辑对撞合龙](analysis/2026-04-25-b-account-collision-synthesis.md)
- [2026-04-22 联邦投顾与GEMINI逻辑对撞深度分析](analysis/2026-04-22-gemini-federal-collision-analysis.md)
- [2026-04-22 全量数据审计报告](analysis/2026-04-22-full-data-audit.md)
- [2026-04-21 SENSEX 泡沫审计协议](analysis/2026-04-21-sensex-bubble-audit.md)
- [2026-04-21 逻辑合龙协议](analysis/2026-04-21-logic-convergence-protocol.md)
- [513910 港股通央企红利ETF — 收割者 vs 被收割者](analysis/513910-harvester-victim-audit.md)

- [M1 Z_atr 阈值回测报告 2026-05-20](analysis/zatr-threshold-backtest-m1-2026-05-20.md) — 全池19标29,096样本，确认-2.0为合理初始阈值，Sharp 0.0508/胜率53.1%，条件④解锁
- [M3 双参数联合优化报告 2026-05-23](analysis/ruins-harvesting-m3-optimization-2026-05-23.md) — 废墟收割M3完成。最优参数-2.50/-1.25，三集回测90笔/假废墟率14.4%/夏普0.35，四标的全量覆盖。2026-05-23签发。

## 🔶 黄金逻辑链

- [黄金逻辑链穿透审计：停火→油价→CPI→加息预期→金价](analysis/gold-logic-chain-stopfire-cpi-2026-05.md) — 五环链物理验证：停火从源头斩断油价推高CPI→加息预期→实际利率上升的完整链条。联邦审计补充30-40%跌幅源于央行反手抛售。金盾V1.4根因补充。2026-05-25入库。

## ⚔️ 决策日志（复盘追溯系统 V1.0）

- [决策日志索引](analysis/decision-log/index.md) — 操作信号记录规则与目录。每笔操作强制记录触发依据/执行参数/实际结果，支撑复盘追溯。2026-05-29上线。
- [2026-05 决策日志](analysis/decision-log/2026-05.md) — 本月操作信号（8笔：QQQ/IVV/CANE/BBJP/MUFG/513910/159302/IAU）
- [2026-05 已否决信号](analysis/decision-log/rejected/2026-05.md) — 路由输出但未执行的信号

## 📊 回测与审计报告

- [锚点有效性全量回测报告 2026-05-16](analysis/anchor-effectiveness-backtest-2026-05-16.md) — 全池19标×8锚点统计效力检验，US10Y跳升>8bp为最有效锚点（5标极显著），SHIBOR 1.70%对A股无预测力，4.50%绝对阈值全池无一显著

## 📰 外部资料来源

- [量化交易教科书：算法、分析、数据、模型和优化](sources/quantitative-trading-textbook-guo2017.md) — 郭新等(2017/2020)，斯坦福/UC Berkeley量化金融教材。覆盖统计模型、投资组合、高频计量、LOB、最优执行、做市、监管等全链路。2026-05-25收录。

## 📰 外部资料来源

- [2026年5月美债历史性抛售深度分析](sources/2026-may-treasury-selloff-analysis.md) — US10Y +12bp/US30Y 5.12%创2007年来新高，驱动机制+历史对标+全球连锁效应。2026-05-18收录。

## 📊 数据基础设施

- [全池21标分析数据覆盖矩阵 V1.0](concepts/data-coverage-matrix-v1.md) — 逐标标注数据来源与自动化率，取数四步流程（P1→P2→P3→P4→P0），违规熔断清单。2026-05-13。
- [Phase 4 全池17标绩效回测报告](analysis/phase4-full-backtest-2026-05-16.md) — 2018-2026年8年回测，2208笔交易，进攻+96.18%/反击+50.24%，合计+146.42%。六大核心发现。2026-05-16。

## 🏷️ 里程碑

- [Phase 3 启动里程碑](concepts/phase3-launch-milestone.md) — 法典 Phase 2 收官 / Phase 3 实战打磨正式启动，2026-05-07
- [2026年2月 "一个狠人"视频 保证金/0DTE/Gamma翻转审计](sources/2026-02-youtube-margin-debt-gamma-flip.md) — 保证金债务1.2256万亿+净信用余额−814亿+Skew 143.78+SPX 6800 Gamma翻转位。联邦法典对账：现有防御层已覆盖大部分风险，建议新增SPX Gamma翻转位+信用利差周度监控。2026-05-22收录。
- [巴西降雨与甘蔗压榨研究 2026-05](sources/brazil-rainfall-sugar-research-2026-05.md) — UNICA/INMET/NOAA/USDA数据汇编，2026/27榨季开局（制糖比32.93%），厄尔尼诺概率88-98%，6-8月才是真正降雨风险窗口
- [2026年强厄尔尼诺概率与巴西雨季预测](sources/2026-el-nino-forecast-brazil-rainfall.md) — NOAA CPC+IRI数据，形成概率96%+，强+极强>50%，峰值在12-2月，巴西北旱南涝典型格局。2026-05-24收录。
- [CANE历史厄尔尼诺涨幅对标分析 2026-05-24](analysis/cane-el-nino-upside-estimate-2026-05-24.md) — 基于2009/2015/2018/2023四次厄尔尼诺事件期间ICE#11糖价涨幅对表，三种情景预估：保守+9~23%/基准+23~50%/乐观+50~90%
- [2026年厄尔尼诺→商品资产传导全链路 V2.0 [已归档]](sources/el-nino-commodity-chain-2026-v2.md) — V2.0版本，已由V3.0取代。2026-05-26入库，2026-05-28归档。
- [2026年厄尔尼诺→商品资产传导全链路 V3.0](sources/el-nino-commodity-chain-2026-v3.md) — ⭐当前版本。V3.0由联邦投顾对撞审计锁定（2026-05-28）。六大核心修正：ICE#11涨幅修正为实际值（230%/133%/56%）、巴西制糖比32.93%独立变量、LNG危机→乙醇溢价链新增驱动、煤炭评级下调为中性偏多、三品种零和资金约束、DXY尾部风险警示。⭐白糖三重共振框架。
- [港股跌跌不休四因共振穿透审计](analysis/hk-market-four-factor-2026-06-19.md) — 守东分享港股分析框架+联邦投顾穿透审计。四因（美元抽水/戴维斯双杀/IPO解禁失血/外资定价）+港元联系汇率结构锁死补充+底部三信号判定。2026-06-19入库。

- [港交所科技100指数2026年半年度调整](sources/hkex-tech100-index-rebalance-2026-05.md) — 调入7只/剔除7只，6月12日生效。同日MSCI/上证50/深证成指等密集调样公告，对全池无直接物理冲击。2026-05-29收录。
- [Jeff Clark：当前黄金调整与1976-1980牛市惊人相似（相关性95%）](sources/gold-correction-1976-parallel-clark-2026-06-11.md) — KitcoNews访谈。Clark绘制两轮牛市走势对比图，相关系数95%。当前-21%回撤在历史正常修正范围。他本人正在积极买入。联邦投顾穿透审计：形态匹配可信，但驱动因子差异决定波动率不同。金盾V1.4四条件全红→右侧等待不变。2026-06-11收录。

## 📊 数据基础设施

- [准备金余额监控协议 V1.0](concepts/reserve-balance-monitor-v1.md) — ⭐2026-06-19入库。准备金余额（美联储总资产−TGA−RRP）每周监控，四级阈值体系。当前$3.111万亿（充裕）。与VIX/US10Y互补形成三维流动性预警。数据源：FRED WRBWFRBL。
- [止损后反手冷却规则 V1.0](concepts/stop-loss-reentry-cooldown-v1.md) — ⭐2026-06-19焊入AGENT.md。全池19标8.5年761笔急跌回测：次日反弹60.1%，但趋势性事件驱动急跌反弹率更低。48h强制冷却+急跌性质二分类判定（超卖型/趋势型）+趋势型额外等待5交易日。禁止「止损即反手」。
- [A股数据四剑客对比矩阵 V2.0](concepts/a-stock-data-triad-v1.md) — Tushare/BaoStock/AKShare/efinance全维度对比。V2.0新增efinance（东财轻量化接口，3,700+ Star，零注册，一行代码，实时行情+基金+期货+可转债全覆盖）。四剑客口诀：「入门BaoStock，日常efinance，探索AKShare，生产Tushare」。2026-06-07更新。
- [Python量化交易全流程工具链 V1.0](concepts/python-quant-toolchain-v1.md) — 六大环节工具链全景（数据/策略/回测/实盘/AI/风控）。联邦审计：已覆盖数据+策略+风控，未覆盖回测框架(VectorBT推荐)+实盘自动下单(永久跳过)。2026-06-14入库。

