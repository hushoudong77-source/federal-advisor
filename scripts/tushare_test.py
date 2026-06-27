import tushare as ts
import os

# 从环境变量读取token，兜底用硬编码
token = os.environ.get("TUSHARE_TOKEN", "5b9c0bfb18b1d6eaa7e31e7aacb10366a6c1a6bdbf9be7e611e2bc9f")
ts.set_token(token)
pro = ts.pro_api()

print("=== Tushare Token 验证 ===")
print(f"Token: {token[:8]}...{token[-4:]}")
print()

# 测试1: 用户信息
try:
    df = pro.query("stock_basic", limit="1")
    print("✅ query(stock_basic) 通过")
except Exception as e:
    print(f"❌ query(stock_basic) 失败: {e}")

# 测试2: fund_daily
try:
    df = pro.fund_daily(ts_code='513910.SH', start_date='20260625', end_date='20260627')
    print(f"✅ fund_daily: {len(df)}条")
except Exception as e:
    print(f"❌ fund_daily: {e}")

# 测试3: us_daily
try:
    df = pro.us_daily(ts_code='QQQ', start_date='20260625', end_date='20260627')
    print(f"✅ us_daily: {len(df)}条")
except Exception as e:
    print(f"❌ us_daily: {e}")

# 测试4: shibor
try:
    df = pro.shibor(start_date='20260625', end_date='20260627')
    print(f"✅ shibor: {len(df)}条")
except Exception as e:
    print(f"❌ shibor: {e}")

# 测试5: us_tycr
try:
    df = pro.us_tycr(start_date='20260625', end_date='20260627')
    print(f"✅ us_tycr: {len(df)}条")
except Exception as e:
    print(f"❌ us_tycr: {e}")

print()
print("=== 验证完成 ===")
