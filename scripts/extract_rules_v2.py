#!/usr/bin/env python3
"""
从 AGENT.md 提取规则 V2 — 扫描所有规则相关段落
使用多种匹配策略：规则名、硬锁、协议、纪律、熔断、阈值等
"""
import re, json

with open('/home/agent/cow/AGENT.md', 'r') as f:
    text = f.read()

lines = text.split('\n')
total = len(lines)
rules = []
rid = 0

# 匹配策略（优先级从高到低）
patterns = [
    # 1. 规则X / 规则X.Y — 描述
    (r'^\*\*规则\s*([A-Z](?:\.[0-9]+)?(?:[A-Z])?(?:\s*[—–-]\s*(.+))?)\*\*', 'rule_explicit'),
    # 2. ### 🔴 硬锁X：
    (r'^###\s*🔴\s*硬锁\s*([零一二三四五六七八九十\d]+)[：:]\s*(.+)', 'hard_lock'),
    # 3. ### 🔴 规则X —
    (r'^###\s*🔴\s*规则\s*([A-Z](?:\.[0-9]+)?)\s*[—–-]\s*(.+)', 'rule_heading'),
    # 4. #### §X.X ... (法典段落)
    (r'^####\s*§(\d+\.\d+)\s+(.+)', 'codex_section'),
    # 5. ### 自检熔断 (独立的熔断规则)
    (r'^###\s*自检熔断', 'self_check'),
    # 6. Step X.X — (执行链步骤)
    (r'^\*\*Step\s+([0-9]+(?:\.[0-9]+)?)\s*[—–-]\s*(.+)\*\*', 'exec_step'),
    # 7. ### 🔶 金盾... (金盾相关)
    (r'^###\s*🔶\s*(.+)', 'gold_shield'),
    # 8. ### 🔴 独立标的买入纪律
    (r'^###\s*🔴\s*独立标的买入纪律', 'independent_discipline'),
    # 9. ### 🔴 FLIN/SMIN/EWY 动量跟随策略
    (r'^###\s*🔴\s*FLIN/SMIN/EWY\s+动量跟随策略', 'momentum'),
    # 10. ### 🔴 止损后反手冷却规则
    (r'^###\s*🔴\s*止损后反手冷却规则', 'stop_loss_cooldown'),
    # 11. 模块十三/十二等
    (r'^###\s*模块\s*([十]+[一二三四五六七八九]?)[：:]*\s*(.+)', 'module'),
    # 12. 博弈态判定
    (r'^│\s*├──\s*博弈态\s*[：:]\s*(.+)', 'game_state'),
    # 13. 五维
    (r'^│\s*├──\s*五维\s*[：:]\s*(.+)', 'five_dim'),
]

for i, line in enumerate(lines):
    for pat, ptype in patterns:
        m = re.match(pat, line)
        if m:
            rid += 1
            if ptype == 'rule_explicit':
                code = m.group(1).strip()
                desc = m.group(2) if m.lastindex >= 2 and m.group(2) else ''
            elif ptype == 'hard_lock':
                code = f'HL{m.group(1)}'
                desc = m.group(2)
            elif ptype == 'rule_heading':
                code = m.group(1)
                desc = m.group(2)
            elif ptype == 'codex_section':
                code = f'§{m.group(1)}'
                desc = m.group(2)
            elif ptype == 'self_check':
                code = 'SELFCHECK'
                desc = '自检熔断规则'
            elif ptype == 'exec_step':
                code = f'Step{m.group(1)}'
                desc = m.group(2)
            elif ptype == 'gold_shield':
                code = 'GOLD'
                desc = m.group(1)
            elif ptype == 'independent_discipline':
                code = 'INDEP_DISC'
                desc = '独立标的买入纪律'
            elif ptype == 'momentum':
                code = 'MOMENTUM'
                desc = 'FLIN/SMIN/EWY动量跟随策略'
            elif ptype == 'stop_loss_cooldown':
                code = 'SL_COOLDOWN'
                desc = '止损后反手冷却规则'
            elif ptype == 'module':
                code = f'MOD{m.group(1)}'
                desc = m.group(2) if m.lastindex >= 2 else ''
            elif ptype == 'game_state':
                code = 'GAMESTATE'
                desc = m.group(1)
            elif ptype == 'five_dim':
                code = 'FIVEDIM'
                desc = m.group(1)
            else:
                code = 'UNKNOWN'
                desc = ''
            
            # 提取上下文
            ctx = '\n'.join(lines[i:min(i+20, total)])
            
            # 提取阈值
            thresholds = re.findall(r'(?:[><=]=?\s*\d+\.?\d*%?|VIX\s*[><]\s*\d+|US10Y\s*[≥>]\s*\d+\.\d+%|ATR\s*[><]\s*\d+\.?\d*%?)', ctx)
            
            rules.append({
                'id': f'R{rid:03d}',
                'code': code,
                'name': desc.strip()[:120],
                'line': i + 1,
                'type': ptype,
                'thresholds': list(set(thresholds))[:10],
            })
            break  # 一行只匹配一个模式

print(f"Total lines: {total}")
print(f"Rules extracted: {rid}")

with open('/home/agent/cow/scripts/rules_v2.json', 'w') as f:
    json.dump(rules, f, ensure_ascii=False, indent=2)

print("Written to scripts/rules_v2.json")

# 按类型统计
from collections import Counter
types = Counter(r['type'] for r in rules)
print("\nBy type:")
for t, n in types.most_common():
    print(f"  {t}: {n}")
