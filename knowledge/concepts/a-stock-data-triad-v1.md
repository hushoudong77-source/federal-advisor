# A股数据四剑客对比矩阵 V2.0 — Tushare / BaoStock / AKShare / efinance

> 2026-05-30 入库 | 2026-06-07 V2.0 追加 efinance
> 用途：为全池数据取数提供P2/P4层备选方案

## 一、核心定位

| 维度 | Tushare Pro | BaoStock | AKShare | **efinance** |
|:---|:---|:---|:---|---:|
| **定位** | 付费机构级API | 免费A股历史K线 | 免费全品类数据聚合 | **东财轻量化接口** |
| **年费** | ¥2200+ | ¥0 | ¥0 | **¥0** |
| **注册** | ✅ 需实名注册 | ❌ 零注册 | ❌ 零注册 | **❌ 零注册** |
| **安装** | pip install tushare | pip install baostock | pip install akshare | **pip install efinance** |
| **API风格** | RESTful JSON | Socket→DataFrame | 函数式→DataFrame | **函数式→DataFrame** |
| **稳定性** | ⭐⭐⭐⭐⭐ 付费保障 | ⭐⭐⭐⭐ 服务端推送 | ⭐⭐⭐ 爬虫型 | **⭐⭐⭐⭐ 东财接口封装** |
| **速度** | 快（秒级返回） | 快（服务端推送） | 慢（爬虫解析） | **快（东财直连）** |
| **一行代码** | ❌ 需token+注册 | ❌ 需login() | ✅ 函数式 | **✅ ef.stock.get_quote_history('600519')** |
| **实时行情** | ❌ 不提供 | ❌ 仅历史 | ✅ 部分 | **✅ 全市场4000+实时行情** |
| **GitHub Stars** | — | 4.2k | 14k | **3,700+** |

> **四剑客选择口诀**："入门 BaoStock，日常 efinance，探索 AKShare，生产 Tushare。"

## 二、覆盖范围实测

### 2.1 全池18标A股ETF覆盖（2026-05-30实测）

| 标的 | 代码 | Tushare fund_daily | BaoStock | AKShare |
|:---|:---|:---:|:---:|:---:|
| 513910 | sh.513910 | ✅ 全量历史 | ✅ 2026起 | ✅ |
| 513180 | sh.513180 | ✅ 全量历史 | ✅ 2026起 | ✅ |
| 588000 | sh.588000 | ✅ 全量历史 | ✅ 2026起 | ✅ |
| 510500 | sh.510500 | ✅ 全量历史 | ✅ 2026起 | ✅ |
| 159302 | sz.159302 | ✅ 全量历史 | ✅ 2026起 | ✅ |
| 518880 | sh.518880 | ✅ 全量历史 | ✅ 2026起 | ✅ |

### 2.2 数据深度关键差异

| 指标 | Tushare | BaoStock | 含义 |
|:---|:---:|:---:|:---|
| ETF历史深度 | **2013年起**（大部分） | **仅2026年起** | ⚠️ BaoStock ETF只有不到半年数据 |
| 个股历史深度 | **2000年起** | **2018年起** | 个股BaoStock深度够用 |
| 分钟线 | ❌ 不提供 | ✅ 5/15/30/60分钟 | BaoStock独有优势 |
| 前复权 | ✅ | ✅ adjustflag=2 | 两者都支持 |
| 当日数据时效 | 18:00后入库 | 收盘后可用 | 基本一致 |

### 2.3 美股ETF覆盖

| 标的 | Tushare us_daily | BaoStock | AKShare |
|:---|:---:|:---:|:---:|
| QQQ/IVV/VTI/VEA等11只 | ✅ | ❌ 仅A股 | ✅ 部分 |

## 三、BaoStock 独有优势

1. **分钟线数据**：5/15/30/60分钟K线 — Tushare不提供，AKShare翻车率高
2. **零门槛**：pip install + bs.login() = 一行代码
3. **指数成分股**：上证50/沪深300/中证500成分股列表 — 实时获取
4. **交易日历**：query_trade_dates() 直接返回交易日列表
5. **速度**：6只ETF同时拉取1.5秒，服务端推送远快于爬虫

## 四、致命短板

| 短板 | 说明 | 对我们影响 |
|:---|:---|:---|
| ❌ ETF数据仅2026年起 | 510500/513910等ETF历史数据只有2026年1月至今 | ⚠️ **致命**：全池回测需要2018年起数据 |
| ❌ 无美股数据 | 不覆盖美股ETF | ⚠️ B账户11只美股无法使用 |
| ❌ 无SHIBOR/美债 | 不覆盖宏观利率数据 | ⚠️ 宏观锚点无法替代 |
| ❌ 无港股数据 | 不覆盖港交所标的 | 不影响（全池A股6只） |

## 五、对联邦取数流程的影响

### 当前取数优先级（不变）

```
P2: Tushare（费率已付）→ 主力
P4: BaoStock → A股ETF分钟线备选 / 指数成分股 / 交易日历
P4: AKShare → 兜底（翻车率高）
```

### 具体场景

| 场景 | 推荐数据源 | 原因 |
|:---|:---|:---|
| 全量回测（2018-2026） | **Tushare** | BaoStock ETF深度不够 |
| 当日/近3月A股行情 | **Tushare 或 BaoStock** | 两者均可，BaoStock更快 |
| 分钟线分析 | **BaoStock** | 唯一提供者 |
| 指数成分股 | **BaoStock** | query_sz50/hs300/zz500 一行获取 |
| 交易日历 | **BaoStock** | query_trade_dates() 直接返回 |
| 基本面/财务数据 | **Tushare** | BaoStock对ETF不返回财务数据 |
| SHIBOR/美债 | **Tushare** | 独家覆盖 |
| 美股ETF | **Tushare** | 独家覆盖 |

## 六、整合建议

```
┌───────────────┐     ┌──────────────────┐
│   Tushare     │ ◄── │ 主力（回测/宏观/美股）│
│  (P2 付费)    │     │  90% 场景         │
└───────┬───────┘     └──────────────────┘
        │                      
        ▼                      
┌───────────────┐     ┌──────────────────┐
│   BaoStock    │ ◄── │ 辅助（分钟线/成分股）│
│  (P4 备选)    │     │  8% 场景          │
└───────┬───────┘     └──────────────────┘
        │                      
        ▼                      
┌───────────────┐     ┌──────────────────┐
│   AKShare     │ ◄── │ 兜底（爬虫翻车率高）│
│  (P4 兜底)    │     │  2% 场景          │
└───────────────┘     └──────────────────┘
```

**一句话**：Tushare 是主食，BaoStock 是维生素片（补分钟线），AKShare 是泡面（饿极了才用）。

## 七、efinance 特色能力矩阵

> 3,700+ Star | pip install efinance | MIT License
> 项目地址：https://github.com/Micro-sheep/efinance

### 7.1 数据覆盖

| 品类 | 接口 | 示例 |
|:---|:---|:---|
| **A股日线** | `ef.stock.get_quote_history('600519')` | 全历史DataFrame |
| **A股分钟线** | `ef.stock.get_quote_history('600519', klt=5)` | 5/15/30/60分钟 |
| **A股周/月线** | `klt=102/103` | 周线/月线 |
| **港股日线** | `ef.stock.get_quote_history('00700')` | 腾讯 |
| **美股日线** | `ef.stock.get_quote_history('AAPL')` | 苹果（支持中文名） |
| **批量获取** | `ef.stock.get_quote_history(['600519','000001'])` | 返回dict |
| **实时行情** | `ef.stock.get_realtime_quotes` | 全市场4000+实时 |
| **龙虎榜** | `ef.stock.get_daily_billboard` | 最新龙虎榜 |
| **ETF日线** | `ef.stock.get_quote_history('513050')` | 中概互联ETF |
| **基金实时估值** | `ef.fund.get_realtime_estimate` | 场外基金 |
| **基金历史净值** | `ef.fund.get_quote_history('110011')` | 易方达中小盘 |
| **基金基本信息** | `ef.fund.get_base_info('110011')` | 基金详情 |
| **期货行情** | `ef.futures.get_quote_history('豆粕主力')` | 商品期货 |
| **可转债行情** | `ef.bond.get_realtime_quotes` | 全市场实时 |
| **可转债K线** | `ef.bond.get_quote_history('113009')` | 广汽转债 |

### 7.2 与pandas-ta的配合

```python
import efinance as ef
import pandas_ta as ta

# 一行拉数据
df = ef.stock.get_quote_history('600519')

# 重命名列（pandas-ta需要标准列名）
df = df.rename(columns={
    '开盘': 'Open', '收盘': 'Close',
    '最高': 'High', '最低': 'Low',
    '成交量': 'Volume'
})

# 一键计算所有技术指标
df.ta.strategy("all")
```

### 7.3 四剑客选择口诀

```
入门 BaoStock，日常 efinance，
探索 AKShare，生产 Tushare。
```

| 工具 | 最适合 | 不适合 |
|:---|:---|:---|
| **efinance** | 日常研究、快速验证、实时行情、基金/期货/可转债 | 详细财报、生产环境大规模使用 |
| **BaoStock** | 入门、分钟线、指数成分股、交易日历 | ETF历史（仅2026起）、美股、宏观 |
| **AKShare** | 探索性分析、另类数据 | 生产环境、高可靠性场景 |
| **Tushare** | 生产环境、全量回测、宏观/A股/美股一站式 | 注册门槛、付费成本 |

### 7.4 对联邦取数流程的影响

efinance 的加入使 P4 层能力大幅提升：

| 场景 | 原方案 | 新方案 |
|:---|:---|:---|
| 全池A股ETF日线 | Tushare fund_daily | **Tushare（主力）+ efinance（验证）** |
| 盘中实时行情 | P0用户投喂 | **efinance 实时行情自动获取** |
| 港股日线 | 无专用API | **efinance 直接获取** |
| 基金净值/估值 | 无 | **efinance 基金模块** |
| 可转债行情 | 无 | **efinance 可转债模块** |
| 期货行情 | 无 | **efinance 期货模块** |

**⚠️ 注意**：efinance 是东财接口的第三方封装，非官方API。稳定性可能受东财接口变动影响。生产环境仍以 Tushare 为主力。

## 八、快速使用参考

### BaoStock 标准调用模板

```python
import baostock as bs
import pandas as pd

bs.login()

# A股ETF日线
rs = bs.query_history_k_data_plus(
    "sh.513910",           # 代码格式：sh/sz + . + 6位代码
    "date,code,open,high,low,close,volume,amount,pctChg",
    start_date="2026-01-01",
    end_date="2026-05-30",
    frequency="d",          # d=日, w=周, m=月, 5/15/30/60=分钟
    adjustflag="2"          # 1=不复权, 2=前复权, 3=后复权
)
data_list = []
while (rs.error_code == '0') and rs.next():
    data_list.append(rs.get_row_data())
df = pd.DataFrame(data_list, columns=rs.fields)

bs.logout()
```

### 代码格式对照

| 市场 | Tushare | BaoStock |
|:---|:---|:---|
| 上海A股 | 600000.SH | sh.600000 |
| 深圳A股 | 000001.SZ | sz.000001 |
| 上海ETF | 513910.SH | sh.513910 |
| 深圳ETF | 159302.SZ | sz.159302 |
| 上证指数 | 000001.SH | sh.000001 |

### 注意

- BaoStock 的 ETF 历史数据仅覆盖 **2026年1月起**，对全量回测不够用
- BaoStock 的 `free()` 方法在 v0.9.1 中已废弃
- 个股历史数据从 2018 年起可用（平安银行/贵州茅台等实测通过）

---

## V3.0 追加 — 腾讯实时行情接口

**2026-06-07 实测接入**，腾讯云服务器可直连（HTTP明文，无SSL握手问题）。

| 维度 | 腾讯 qt.gtimg.cn |
|:---|:---|
| 定位 | **P4层实时行情补充源** |
| 协议 | HTTP GET，明文 |
| 鉴权 | 零注册，零密钥 |
| 覆盖 | A股(沪深) + 港股 + 美股 |
| 返回格式 | 类JS变量赋值，`~`分隔文本 |
| 延迟 | Level-1实时，3-5秒 |
| 批量 | 逗号拼接，一次请求全池17标 |
| 历史K线 | ❌ 不覆盖 |
| 腾讯云可用 | ✅ **已实测通过** |

**取数定位**：
- P0/P1 投喂 + P2 Tushare 日线 → 主力
- **腾讯实时** → P4层盘中自动拉取，校验规则K P0覆写
- 不替代 Tushare（无历史K线、无SHIBOR、无美债）

**已预装脚本**: `scripts/qt_realtime.py`
