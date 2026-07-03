import urllib.request
import json

# 全池20标腾讯实时行情
# 美股代码对照：腾讯格式 usXXX（如 usVEA, usQQQ）
# A股代码对照：腾讯格式 sz159530, sh513910 等

symbols = [
    # 美股12只
    ("VTI", "usVTI"),
    ("VEA", "usVEA"),
    ("QQQ", "usQQQ"),
    ("IVV", "usIVV"),
    ("IAU", "usIAU"),
    ("BBJP", "usBBJP"),
    ("MUFG", "usMUFG"),
    ("EWY", "usEWY"),
    ("VNM", "usVNM"),
    ("FLIN", "usFLIN"),
    ("SMIN", "usSMIN"),
    ("BOTZ", "usBOTZ"),
    # CANE（不入池但持仓展示需要）
    ("CANE", "usCANE"),
    # A股8只
    ("588000", "sh588000"),
    ("513180", "sh513180"),
    ("513910", "sh513910"),
    ("510500", "sh510500"),
    ("518880", "sh518880"),
    ("512100", "sh512100"),
    ("510880", "sh510880"),
    ("159530", "sz159530"),
]

codes = [s[1] for s in symbols]
url = "http://qt.gtimg.cn/q=" + ",".join(codes)

try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("gbk")
    
    results = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        # 格式: v_usVTI="1~VTI~367.12~..."
        parts = line.split("~")
        if len(parts) < 5:
            continue
        
        # 提取代码
        code_part = parts[0].split("=")[0]  # v_usVTI or v_sh588000
        qt_code = code_part.replace("v_", "")
        
        name = parts[1]
        price = parts[3]
        change_pct = parts[5] if len(parts) > 5 else "N/A"
        prev_close = parts[4] if len(parts) > 4 else "N/A"
        high = parts[33] if len(parts) > 33 else "N/A"
        low = parts[34] if len(parts) > 34 else "N/A"
        
        # 映射回联邦代码
        federal_code = None
        for fed, qt in symbols:
            if qt == qt_code:
                federal_code = fed
                break
        
        if federal_code:
            results[federal_code] = {
                "name": name,
                "price": price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "high": high,
                "low": low,
            }
    
    # 按联邦代码顺序输出
    for fed, _ in symbols:
        if fed in results:
            r = results[fed]
            print(f"{fed:8s} | {r['name']:20s} | {r['price']:>10s} | {r['change_pct']:>8s}%")
        else:
            print(f"{fed:8s} | {'N/A':20s} | {'N/A':>10s} | {'N/A':>8s}")

except Exception as e:
    print(f"ERROR: {e}")
