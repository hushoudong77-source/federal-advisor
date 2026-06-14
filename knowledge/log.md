## [2026-05-27] ingest | 守东量价交易系统 V1.0
## [2026-05-11] cleanup | 知识库大清理 → 改造准备
- 删除 61 个已作废/已覆盖文件（124→63）
- 删除所有法典历史版本（14个 ceo-execution-codex-v20.xx）
- 删除所有双轨配置历史版本（V1.2/V2.0/V3.3/V4.0/V4.2/V5.5）
- V5.6 64KB → 拆分为 5 个组件文件（v56/ 目录），总 28KB，粒度匹配 RAG 召回
  - v56-constitution.md（3KB）— §0 固定层宪法
  - v56-routing.md（7KB）— §2 路由判断
  - v56-spearhead.md（4KB）— §3.1 进攻策略
  - v56-counterpunch.md（8KB）— §3.2 反击策略
  - v56-macros.md（6KB）— §1 数据输入 + §4 宏观闸 + §5 执行闭环 + 快捷指令
- 删除所有实体开火档案（22个，参数已内嵌至 V5.6 §3.2）
- 删除 Spearhead/Counterpunch/Infrastructure 独立文件（已内嵌 V5.6）
- 删除回测框架历史版本（V1.0/V1.1简报/V1.1完整）
- 删除 templates 旧版（V20.31.5/V20.31.6）
- 删除 sources/ 过期文件（IATA/沃什听证会）
- 重写 index.md，V5.6 为唯一执行真源
- 知识库大小：2.1MB → 约 1.3MB

## [2026-05-25] compile | 量化交易教科书知识体系编译（5页）
- 已存页面：knowledge/sources/quantitative-trading-textbook-guo2017.md（全书概览，5/25入库）
- 新增：knowledge/concepts/parameter-uncertainty-dynamic-portfolio-v1.md（§3.3.6 参数不确定性 → 置信度分数的理论地基）
- 新增：knowledge/concepts/statistical-models-trading-v1.md（§2 统计模型 → 缩减技术/多重检验/Black-Litterman/BL融合潜力）
- 新增：knowledge/concepts/realized-volatility-v1.md（§4.3 RV → ATR14互补，波动率预警链）
- 新增：knowledge/concepts/optimal-execution-almgren-chriss-v1.md（§6.1-6.3 Almgren-Chriss → CANE建仓/各量级执行建议）
- 新增：knowledge/concepts/order-book-hft-v1.md（§5+§7 LOB+Hawkes+做市模型 → 低流动性标的价格行为解释）
- 新增：knowledge/concepts/black-litterman-federal-v1.md（§2.4.2 BL → 固定层权重优化的融合方案，当前不实施的条件判断）
- 总文件数：78 → 84
- 与联邦投顾的对撞结论已内嵌至每个页面的"对联邦意义"段落
- Source: 用户分享链接（txt文档）
- Path: knowledge/sources/quantitative-trading-textbook-guo2017.md
- Content: 郭新等(2017/2020)量化金融教材，8章完整知识框架：统计模型与NPEB法则、投资组合管理与Black-Litterman、高频计量与已实现波动率、LOB分析与Hawkes过程、最优执行(Almgren-Chriss)、做市与SOR、监管与风控

## [2026-04-17] ingest | 大师战术精华
- Source: 用户分享文档
- Path: knowledge/concepts/trading-masters-tactics.md
- Content: 交易心理学、宏观周期、5M量化框架、技术择时、头寸管理、风控底线、SOP清单

## [2026-04-19] ingest | 全球资产交易系统V13.1
- Source: 用户分享文档
- Path: knowledge/concepts/global-asset-trading-system-v13.md
- Content: 紧缩版交易系统，DXY/US10Y宏观哨兵，ATR×3.0/2.0/1.5止损参数，熔断阶梯，执行口诀

## [2026-04-19] ingest | 熔断法典6.0
- Source: 用户分享文档
- Path: knowledge/concepts/circuit-breaker-codex-v6.md
- Content: 投资协作矩阵，三大情报中心对抗式审计，Weinstein阶段论，MA120/MA233拦截，ATR动态波动率，三级预警，SGOV防御中心，复盘准则
## 2026-04-28
- **新增** MUFG/BBJP/FLIN/SMIN/EWY/EWU 6个开火档案到 entities/
- **更新** index.md 添加6条Entities索引
- **更新** VNM开火档案（基于OCR数据二次校准，确认不变）
- **新增** [2026-04-28 日元159.29汇率重力对撞](../analysis/2026-04-28-jpy-159-collision.md) 到 analysis/
- **更新** MUFG开火档案：汇率重力修正，买入区间缩窄至$17.07~$17.30，开火信号改为限价伏击模式

## [2026-05-25] analyze | 黄金逻辑链穿透审计 + 金盾V1.4根因补充
- **新增** [黄金逻辑链穿透审计：停火→油价→CPI→加息预期→金价](../analysis/gold-logic-chain-stopfire-cpi-2026-05.md) — 基于守东供弹文章的五环链验证+联邦审计补充（30-40%跌幅源于央行反手抛售被忽略）
- **更新** 金盾总纲V1.4核心发现段：补充2023年后C1-C4失效的深层根因链（油价→CPI→加息预期→实际利率→黄金持有成本），并标注停火若落地的反转条件

## [2026-05-26] ingest | 厄尔尼诺→商品资产传导全链路
- **新增** [2026年厄尔尼诺→商品资产传导全链路 V1.0](../concepts/el-nino-commodity-chain-2026-v1.md) — 基于守东投喂国盛证券徐文辉5/20报告+NOAA CPC/IRI预测+历史13次厄尔尼诺事件复盘。覆盖白糖(6年周期见底+与CANE协议直接对账)、棕榈油(滞后4Q)、天然橡胶(滞后5Q)、棉花(需求库存约束)、煤炭/电力(高温传导链)。含9项风险限制+全链路时间线2026-2027。
- **更新** CANE跟踪协议V1.1 — 追加6年周期底部框架+厄尔尼诺共振历史对标到基本面驱动框架段。
## [2026-06-02] synthesize | ETF动量轮动策略 — RPS排名 vs 法典对撞
## [2026-06-14] ingest | Python量化交易全流程工具链 V1.0
