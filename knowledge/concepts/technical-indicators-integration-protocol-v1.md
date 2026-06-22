# 技术指标自主计算集成协议 V1.3

> **版本**: V1.3（TD9全策略嵌入+确认条件硬化 · 2026-06-22 焊入）  
> **创建时间**: 2026-05-02  
> **地位**: 对 V5.8.2r32.0 法典的指标计算硬化补丁  
> **前置条件**: Tushare日线自算（P2级），无需守东投喂OHLCV  
> **数据源**: Tushare pro.us_daily() / pro.fund_daily() 日线  
> **当前状态**: ✅ MACD 已激活 / ✅ TD9 计算引擎已就绪（scripts/calc_td9.py）

---

## 一、指标体系与最小数据需求

| 指标 | 公式 | 最小序列长度 | 启动条件 |
|:---|:---|:---:|:---|
| **ATR(14)** | Wilder平滑 True Range | 14 日 | 积累满14日自动输出 |
| **RSI(14)** | Wilder平滑 RS | 14 日 | 积累满14日自动输出 |
| **MACD(12,26,9)** | EMA12-EMA26, DEA=EMA9(DIF) | 26 日 | 积累满26日自动输出 |
| **TD Setup（九转·结构）** | C_i < C_{i-4} 计数 1-9 | 9 日 | 积累满9日基础启动 |
| **TD Countdown（九转·倒计时）** | C_i ≤ L_{i-2} 计数 1-13 | 22 日 | Setup完成后启动，满22日完整 |
| **MA20/MA60/MA120** | 简单移动平均 | 20/60/120 日 | 积累满对应天数 |
| **布林带(20,2)** | MA20 ± 2×σ | 20 日 | 积累满20日 |
| **成交量异动** | V > MA(V,20)×1.5 | 20 日 | 积累满20日 |

### 指标启动时间线

```
Day 1-8:   纯序列积累（静默期）
Day 9:     TD Setup 基础启动（买入/卖出结构 1-9 计数）
Day 14:    ATR(14) + RSI(14)
Day 20:    MA20 + 布林带 + 成交量异动
Day 22:    TD Countdown 完整（Setup 9 + Countdown 13）
Day 26:    MACD(12,26,9) 全量
Day 60:    MA60
Day 120:   MA120
```

### ⚡ 统帅供弹加速机制（可跳过等待期）

守东可直接投喂任何标的的现成指标值（来自行情软件），即刻武装决策引擎：

```
守东供弹 → 即刻启用
├── ATR(14) = X  →  止损/N股数精算即刻生效
├── RSI(14) = Y  →  开火评分/超买拦截即刻生效
├── MACD DIF/DEA/柱 = Z  →  缠论背驰/阶段判定即刻生效
├── TD Setup 数字 = N  →  九转衰竭判定即刻生效
└── MA60/MA120 = M  →  均线位阶即刻生效
```

**约束**：
- 供弹值遵循 P0 规则（守东给的=真值），来源标注 `[指标数据: 统帅供弹]`
- 后台序列仍在自主积累（等待未来自主计算覆盖），供弹不中断序列
- 供弹值与自主计算值并存时，以 P0 供弹值为准，自主计算值作校验

---

## 二、法典条款指标嵌入

### 2.1 ATR(14) 嵌入点

#### 4.2 基础动态止损（核心）

```
止损位 = 买入价 - k × ATR(14)

k 值由 ER 效率比决定：
├── ER > 0.6（强趋势）→ k = 1.5
├── 0.3 ≤ ER ≤ 0.6（常态）→ k = 2.0
└── ER < 0.3（震荡）→ k = 2.7
```

**计算流程**：
1. 从 OHLCV 序列计算 True Range = max(H-L, |H-C_prev|, |L-C_prev|)
2. Wilder 平滑：ATR_t = (ATR_{t-1} × 13 + TR_t) / 14
3. 初始 ATR 为前14日 TR 的简单平均
4. 输出精确到美分/分

#### 4.5 跳空隔离

```
触发：跳空跌幅 > 2 × ATR(14)
动作：判定为"物理性逻辑失效"，全清撤离 SGOV
```

#### 2.1.5 Vol-Adjusted 阈值协议

```
动态阈值 = 95.50 + (1 - ATR_标的 / ATR_QQQ) × 0.60
硬顶边界：[95.20, 95.80]
```

**ATR 取值**：20日 ATR（价格绝对振幅），与标的现价同单位。

---

### 2.2 RSI(14) 嵌入点

#### 开火条件判定（加权评分制）

| RSI 区间 | 评分 | 含义 |
|:---|:---:|:---|
| RSI < 30 | +20 分 | 超卖，废墟收割信号 |
| 30 ≤ RSI < 40 | +15 分 | 偏弱，可能入场区间 |
| 40 ≤ RSI < 45 | +10 分 | 正常偏低 |
| 45 ≤ RSI < 55 | +5 分 | 中性 |
| 55 ≤ RSI < 70 | +0 分 | 正常偏高 |
| RSI ≥ 70 | -10 分 | 超买，开火拦截 |

**计算流程**：
1. 14日上涨平均涨幅 / 14日下跌平均跌幅 = RS
2. RSI = 100 - 100/(1+RS)
3. Wilder 平滑（非简单平均）

#### 废墟收割协议 V1.1 判定

```
RSI < 30 → 超卖确认，废墟收割优先级+1
RSI < 25 → 极度超卖，允许扩大先锋仓位至 1.5×
```

#### 开火档案 QQQ 附加条件

```
RSI < 60 → 开火条件之一
RSI 非极值（< 70）→ 开火允许
```

---

### 2.3 MACD(12,26,9) 嵌入点

#### 2.3 缠论物理准则（核心）

```
背驰判定 = MACD 面积对比
├── 顶背驰：价格新高但 MACD 柱面积缩小 → 卖出信号
├── 底背驰：价格新低但 MACD 柱面积缩小 → 买入信号（需 IEF 解锁）
└── 面积计算：DIF 与 DEA 之间的柱状面积积分
```

#### Weinstein 阶段判定（辅助）

| MACD 信号 | 阶段判定辅助 |
|:---|:---|
| DIF > DEA 且均在零轴上 | Stage 2 确认 |
| DIF 下穿 DEA（死叉） | Stage 3 预警 |
| DIF < DEA 且均在零轴下 | Stage 4 确认 |
| DIF 上穿 DEA（金叉） | Stage 1 转 Stage 2 信号 |

#### 开火条件判定

```
MACD 金叉（DIF 上穿 DEA）→ 开火评分 +15
MACD 死叉（DIF 下穿 DEA）→ 开火评分 -15
MACD 零轴上方 → +5（多方主导）
MACD 零轴下方 → -5（空方主导）
```

#### FTD 深度校验（2.3.1）

```
FTD 确认日 + MACD 金叉 → 增强确认信号
FTD 确认日 + MACD 死叉 → 削弱，可能为诱多
```

---

### 2.4 TD9 九转序列（V1.3硬化版 — 2026-06-22 焊入）

#### 计算逻辑（修正命名 — V1.2的买入/卖出命名与原版反向，V1.3纠正）

**低位9转（下跌衰竭 → 买入信号）**：
```
计数条件: C_i < C_{i-4}（当日收盘 < 4天前收盘）
├── 连续满足即计数 +1
├── 不满足 → 中断归零，重新开始
├── 计数达到 9 → 低位9转完成 → 🟡「下跌衰竭」
└── 数据源: P2 Tushare日线自算（scripts/calc_td9.py）
```

**高位9转（上涨衰竭 → 卖出/预警信号）**：
```
计数条件: C_i > C_{i-4}（当日收盘 > 4天前收盘）
├── 连续满足即计数 +1
├── 不满足 → 中断归零
├── 计数达到 9 → 高位9转完成 → 🟡「上涨衰竭预警」
└── 数据源: P2 Tushare日线自算（scripts/calc_td9.py）
```

#### 确认条件（三条件AND，缺一不可）

| 条件 | 规则 | 阈值 | 逻辑 |
|:---|:---|:---|:---|
| **C1 结构完整性** | 低位9转计数=9 | 无弹性——必须是9，8不行 | 第9天是衰竭确认日 |
| **C2 缩量确认** | 第9天成交量 < 20日均量的80% | VOL(9) / MA(VOL,20) < 0.8 | 空头砸不动——缩量=卖方力竭 |
| **C3 小实体确认** | 第9天实体 ≤ ATR(14)的30% | \|C[9]−O[9]\| / ATR14 < 0.3 | 小实体=多空暂时平衡 |

**为什么不是原版Countdown 13**：Countdown需要22天完整序列且条件更复杂（C_i≤L_{i-2}），在联邦策略中延迟太大。Setup=9+确认条件已足够。

#### 全策略嵌入位置

##### 进攻策略

```
C1-C4 AND全部满足
    │
    ├── 低位9转已完成 + 三确认 → 🟢 绿灯，正常开火
    ├── 低位9转进行中(计数≥6) → 🟡 等待9转完成确认
    ├── 高位9转已完成 → ⚠️ 标注「TD9高位衰竭预警」但不拦截
    │   进攻是趋势跟随，高位9转与C4回调方向一致——C4是回调买入，
    │   高位9转是上涨衰竭——两者矛盾时标注预警，不否定C4
    └── 无信号 → 不强制，C1-C4本身通过
```

##### 反击策略（主力战场）

```
R0-R2 AND全部满足，价格触及买入区间
    │
    ├── 低位9转已完成 + 三确认 ✅ → 🟢 绿灯，正常两层建仓
    ├── 低位9转已完成但缩量/小实体不满足 → 🟡 正常两层（不砍仓位）
    │   逻辑：TD9不替代买入区间——区间是第一性，TD9是第二性
    ├── 低位9转计数≥6但未完成 → 🟡 等待完成，或价格触及第二层买入区间
    ├── 低位9转与买入区间方向矛盾（计数归零=趋势加速下跌）
    │   → ⛔ 暂停，等矛盾解除
    └── 无信号 → 🟡 正常按反击买入区间执行
```

##### 金盾策略

```
金盾正统四条件全绿 或 金盾战术前置三条件AND
    │
    ├── 低位9转已完成 + 三确认 → 🟢 正常仓位
    ├── 低位9转已完成但无确认 → 🟡 仓位减半（金盾比反击更保守）
    └── 无信号 → 不强制
```

##### 固定层（VTI/VEA）

```
MA60−4×ATR区间触发
    │
    ├── 低位9转已完成 + 确认 → 🟢 正常执行
    └── 无信号 → 不强制，固定层不依赖TD9
```

##### 独立标的（CANE等）

```
D1-D3 AND全部满足
    │
    ├── 低位9转已完成 + 三确认 → 🟢 正常建仓
    ├── 低位9转进行中 → 🟡 等待完成
    └── 无信号 → 🟡 不强制，D1-D3本身已过滤
```

#### 输出格式（嵌入 /开火 /进攻 /反击 正文）

```
## 🔢 TD9 辅助确认

| 标的 | TD9状态 | 计数 | 缩量(<0.8) | 小实体(<0.3×ATR) | 确认 | 仓位调整 |
|:---|:---|:---:|:---:|:---:|:---:|:---|
| 513910 | 低位9转完成 | 9 | 0.72 ✅ | 0.22 ✅ | 🟢 全确认 | 正常两层 |
| 510500 | 低位9转进行中 | 7 | — | — | 🟡 等待 | 等计数=9 |
| QQQ | 高位9转完成 | 9 | 1.15 ❌ | 0.45 ❌ | 🔴 未确认 | ⚠️高位衰竭预警 |

├── 全确认标的: N个 — 正常仓位
├── 等待确认标的: M个 — 等待或仓位不变
└── 预警标的: K个 — 进攻策略高位9转标注预警
```

#### 计算引擎

- **脚本**: `/home/agent/cow/scripts/calc_td9.py`
- **输入**: Tushare日线DataFrame（trade_date, close, open, high, low, vol）
- **输出**: td9_status / td9_count / c1_pass / c2_pass / c3_pass / td9_confirmed / td9_direction
- **更新频率**: 每次 `/开火` `/进攻` `/反击` 触发时自算，与ATR/MA/MACD同步
- **新鲜度校验**: 规则M.1强制——TD9计数必须基于Tushare最新日线

#### 与现有协议的冲突检查

| 现有条款 | 冲突？ | 处理 |
|:---|:---|:---|
| 规则L（P5禁用） | 否 | TD9基于Tushare日线自算，P2级 |
| 规则M.1（新鲜度） | 否 | 与ATR/MA/MACD同步重算 |
| 反击策略C3独立参数 | 否 | TD9是辅助确认，不修改参数 |
| 大势确定性五维评估 | 否 | TD9在五维评估通过后执行 |

---

## 三、每日投喂处理 SOP

### 3.1 数据入库

```
每次守东投喂 → 解析 OHLCV → 追加至内存序列
├── 美股 ETF：追加至 OHLCV 序列（key = 代码）
├── A股 ETF：追加至 OHLCV 序列（key = 代码）
├── 锚点指数：追加至 OHLCV 序列（key = 代码）
└── 写入当日 memory/YYYY-MM-DD.md
```

### 3.2 序列状态检查

```
每次入库后 → 检查序列长度
├── < 14 日 → 仅存储，标注"指标数据不足"
├── ≥ 14 日 → 自动输出 ATR(14) + RSI(14)
├── ≥ 20 日 → 追加 MA20 + 布林带 + 成交量异动
├── ≥ 26 日 → 全量启动 MACD(12,26,9)
├── ≥ 60 日 → 追加 MA60
└── ≥ 120 日 → 追加 MA120
```

### 3.3 自动产出

**满9日后，每次投喂自动输出**：

```
⚙️ 技术指标日报
├── 宏观锚点：DXY/IEF/VIX/XAU/布伦特 的 RSI + ATR
├── 持仓标的：IAU/518880/513910 的全指标
├── 核心池：21标的 RSI 超买超卖扫描
├── 废墟雷达：RSI<30 标的自动标记
├── 九转信号：TD Setup=9 / Countdown=13 标的自动标记
├── 信号交叉：MACD金叉/死叉（满26日后）
└── 开火评分：综合 RSI + MACD + TD + 均线 自动计算
```

---

## 四、扫描报告模板嵌入

### 嵌入位置：第二章「核心池全景扫描」

在现有21大锚点表格后，追加指标摘要行：

```
### 技术指标快照（基于守东投喂序列）

| 标的 | RSI(14) | ATR(14) | MACD信号 | TD Setup | 量比 |
|:---|---:|---:|:---|:---:|:---:|
| QQQ | 58.2 | 12.45 | DIF>DEA 🟢 | 买入3 | 1.06 |
| IAU | 42.1 | 1.85 | 死叉 🔴 | 卖出7 | 2.17 |
| ... | ... | ... | ... | ... | ... |
```

### 嵌入位置：第三章「首席审计官证伪」

```
3.5 技术指标证伪
- RSI 背离审计：价格走势 vs RSI 是否出现顶/底背离
- ATR 波动率审计：当前 ATR 是否处于极端扩张/收缩
- MACD 背驰审计：缠论面积对比是否支持当前方向
- TD 九转审计：Setup/Countdown 是否与当前持仓方向矛盾
```

---

## 五、分析报告模板嵌入

### 嵌入位置：第二章「Sentinel-01 物理位阶审计」

在均线光谱表后追加：

```
**动能信号**

| 指标 | 数值 | 判定 |
|:---|---:|:---|
| RSI(14) | [数值] | 🔴超买 / 🟢正常 / 🟡超卖 |
| ATR(14) | [数值] | 波动率 [扩张/收缩/正常] |
| MACD DIF | [数值] | 🟢金叉 / 🔴死叉 / 🟡黏合 |
| MACD 柱 | [数值] | 多头/空头/收敛 |
| TD Setup | [买入N/卖出N] | 🟡衰竭预警 / 🟢无信号 |
| TD Countdown | [N/13] | 🔴反转确认 / 🟡进行中 |
| 量比 | [数值] | 🔴放量 / 🟢正常 / 🟡缩量 |
```

---

## 六、计算函数规范（Python 沙盒）

### ATR(14)

```python
def calc_atr(highs, lows, closes, period=14):
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    # Wilder 平滑
    atr = sum(tr_list[:period]) / period  # 初始值
    result = [None] * period + [atr]
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        result.append(atr)
    return result  # 前 period-1 项为 None
```

### RSI(14)

```python
def calc_rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    # Wilder 平滑
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_list = [None] * period
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
    rsi_list.append(100 - 100/(1+rs))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
        rsi_list.append(100 - 100/(1+rs))
    return rsi_list
```

### MACD(12,26,9)

```python
def calc_macd(closes, fast=12, slow=26, signal=9):
    def ema(data, period):
        result = [data[0]]
        k = 2 / (period + 1)
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result
    
    ema12 = ema(closes, fast)
    ema26 = ema(closes, slow)
    dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    dea = ema(dif, signal)
    # 柱状线 = 2×(DIF - DEA)
    macd_bar = [2 * (d - e) for d, e in zip(dif, dea)]
    return dif, dea, macd_bar
```

### TD Sequential（九转序列）

```python
def calc_td_sequential(closes, highs, lows, setup_compare=4, countdown_compare=2):
    """
    计算九转序列 Setup 和 Countdown
    返回: setup_buy[], setup_sell[], cd_buy[], cd_sell[]
    """
    n = len(closes)
    setup_buy = [0] * n      # 买入结构计数（顶部衰竭）
    setup_sell = [0] * n     # 卖出结构计数（底部衰竭）
    cd_buy = [0] * n         # 买入 Countdown
    cd_sell = [0] * n        # 卖出 Countdown
    
    buy_setup_complete = False   # 买入 Setup 是否达到9
    sell_setup_complete = False  # 卖出 Setup 是否达到9
    buy_cd_start = -1
    sell_cd_start = -1
    
    for i in range(n):
        # === Setup 计数 ===
        if i >= setup_compare:
            # 买入 Setup: C_i < C_{i-4}
            if closes[i] < closes[i - setup_compare]:
                setup_buy[i] = setup_buy[i-1] + 1
            else:
                setup_buy[i] = 0  # 中断归零
            
            # 卖出 Setup: C_i > C_{i-4}
            if closes[i] > closes[i - setup_compare]:
                setup_sell[i] = setup_sell[i-1] + 1
            else:
                setup_sell[i] = 0  # 中断归零
            
            # 记录 Setup 完成点
            if setup_buy[i] == 9 and not buy_setup_complete:
                buy_setup_complete = True
                buy_cd_start = i
            if setup_sell[i] == 9 and not sell_setup_complete:
                sell_setup_complete = True
                sell_cd_start = i
        
        # === Countdown 计数 ===
        if buy_setup_complete and i >= buy_cd_start + 1 and i >= countdown_compare:
            # 买入 Countdown: C_i ≤ L_{i-2}
            if closes[i] <= lows[i - countdown_compare]:
                cd_buy[i] = cd_buy[i-1] + 1
            else:
                cd_buy[i] = cd_buy[i-1]  # 不中断但也不计数
            
            # 取消条件
            if cd_buy[i] > 0 and closes[i] > lows[i - countdown_compare]:
                # 连续不满足 → 可能取消（需进一步判定）
                pass
        
        if sell_setup_complete and i >= sell_cd_start + 1 and i >= countdown_compare:
            # 卖出 Countdown: C_i ≥ H_{i-2}
            if closes[i] >= highs[i - countdown_compare]:
                cd_sell[i] = cd_sell[i-1] + 1
            else:
                cd_sell[i] = cd_sell[i-1]
    
    return setup_buy, setup_sell, cd_buy, cd_sell
```

---

## 七、数据不足时的降级协议

| 序列长度 | 可用指标 | 降级动作 |
|:---:|:---|:---|
| < 9 日 | 无 | 标注"技术指标数据不足，需继续投喂" |
| 9-13 日 | TD Setup（1-9） | ATR/RSI/MACD/布林带/MA20 暂不可用 |
| 14-19 日 | TD Setup + ATR(14) + RSI(14) | TD Countdown 不完整 / MACD/布林带/MA20 暂不可用 |
| 20-21 日 | + MA20 + 布林带 + 量比 | TD Countdown 不完整 / MACD 暂不可用 |
| 22-25 日 | + TD Countdown 完整 | MACD 暂不可用 |
| 26-59 日 | + MACD(12,26,9) | MA60 暂不可用 |
| 60-119 日 | + MA60 | MA120 暂不可用 |
| ≥ 120 日 | 全量 | 所有指标可用 |

**在报告中标注**：`[指标数据: Day N/26，当前可用: TD Setup/ATR/RSI/MA20/布林带/MACD]`

---

## 八、与现有外部数据源的互锁

### 优先级

```
守东投喂 OHLCV（P0） > mx-data（A股补充） > Yahoo Finance（美股补充）
```

### 冲突处理

- 守东投喂的 OHLCV 为 P0 最高权威
- mx-data/Yahoo 仅用于补全守东未投喂的标的
- 若外部数据与投喂数据冲突 → P0 覆盖，标注偏差

### 首次启动时的历史数据补充

- 若守东愿意提供历史 OHLCV 数据（如最近14-26天的日线），可跳过等待期直接启动
- 若无历史数据 → 从 Day 1 开始积累

---

---

## 九、MACD 嵌入日常扫描模板（V1.2 新增 · 2026-05-07 激活）

### 嵌入位置：第二章「全池物理位阶扫描」表后

每次 `/扫描` 指令输出全池价格表后，**强制追加 MACD 状态摘要**：

```
### MACD 动能扫描

| 标的 | DIF | DEA | 柱 | 零轴 | 信号 |
|:---|:---|:---|:---|:---|:---|
| XXX | 0.0623 | 0.0476 | +0.0295 | 零轴上 | 多头增强↑ |
```

### 信号灯映射

| MACD 状态 | 信号灯 | 与买入区间的联动 |
|:---|:---:|:---|
| 零轴上 + 多头增强 + 金叉 | 🟢 动能确认 | 区间内 → 开火信号增强 |
| 零轴上 + 多头增强（无金叉） | 🟢 偏多 | 区间内 → 正常开火 |
| 零轴下 + 空头增强 + 死叉 | 🔴 动能否定 | **区间内也黄牌警告** — 均值回归陷阱风险 |
| 零轴下 + 空头收敛 | 🟡 筑底 | 区间内 → 可开火但仓位减半 |
| 零轴下 + 多头转正（刚金叉） | 🟡 转折信号 | 区间内 → 可开火，这是最优场景 |
| 零轴上 + 空头增强（刚死叉） | 🔴 动能转弱 | 区间内 → 暂停开火，等二次确认 |

### 证伪联动（第三章嵌入）

首席审计官在证伪阶段强制检查：
- **均值回归陷阱**：价格在买入区间内但 MACD 零轴下 + 空头增强 → 红牌拦截
- **顶背驰**：价格创新高但 MACD 柱面积缩小 → 持仓标的触发止盈加速
- **底背驰**：价格创新低但 MACD 柱面积缩小 → 废墟收割优先级+1

### 执行脚本

```python
# MACD 计算 + 信号判定（已固化至 /home/agent/cow/tmp/）
# 每次扫描前运行：python3 calc_macd_all.py
# 数据源：a_etf_full_ohlcv.json / us_etf_full_ohlcv.json
```

---

## 签章

**编制**: 全球资产管理部 · 首席执行官  
**核准**: 联邦四线程全量审计  
**生效**: 2026-05-02 起，每次守东投喂后自动执行  
**版本**: V1.2 — MACD 纳入日常扫描（2026-05-07），零轴下+空头增强=均值回归陷阱红牌拦截
