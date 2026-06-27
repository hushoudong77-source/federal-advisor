#!/usr/bin/env python3
"""从 AGENT.md 全文中提取所有规则，输出到 rules.json"""
import re
import json

def classify_rule(code, ctx):
    if 'A' <= code[0] <= 'M' or code[0] == 'N' or code[0] == 'O' or code[0] == 'P':
        return 'data_module'
    if '硬锁' in ctx or '人格' in ctx:
        return 'personality_lock'
    if '金盾' in ctx or 'IAU' in ctx or '518880' in ctx:
        return 'gold_shield'
    if '进攻' in ctx or 'Spearhead' in ctx:
        return 'spearhead'
    if '反击' in ctx or 'Counterpunch' in ctx:
        return 'counterpunch'
    if '博弈' in ctx or 'VIX' in ctx:
        return 'game_state'
    if '五维' in ctx:
        return 'five_dim'
    if '止损' in ctx or '反手' in ctx:
        return 'stop_loss'
    if '废墟' in ctx:
        return 'ruins'
    if '独立标的' in ctx or 'CANE' in ctx:
        return 'independent'
    if '动量' in ctx or 'FLIN' in ctx or 'SMIN' in ctx or 'EWY' in ctx:
        return 'momentum'
    if '固定层' in ctx or 'VEA' in ctx or 'VTI' in ctx:
        return 'fixed_layer'
    if '资金曲线' in ctx or '规则A' in ctx or '规则B' in ctx or '规则C' in ctx:
        return 'capital_curve'
    if '宏观' in ctx or '危机' in ctx:
        return 'macro_crisis'
    if '中国' in ctx or 'DR007' in ctx or '锚点' in ctx:
        return 'china_anchor'
    if '回测' in ctx:
        return 'backtest'
    return 'general'

def extract_condition(ctx):
    conds = []
    for pattern in [
        r'触发条件[：:]\s*(.+?)(?=\n\n|\n\*|$)',
        r'场景[：:]\s*(.+?)(?=\n\n|\n\*|$)',
        r'触发[：:]\s*(.+?)(?=\n\n|\n\*|$)',
        r'规则[：:]\s*\n\s*(.+?)(?=\n\n|\n\*\*|$)',
    ]:
        m = re.search(pattern, ctx, re.DOTALL)
        if m:
            conds.append(m.group(1).strip()[:200])
    return conds[:3] if conds else []

with open('/home/agent/cow/AGENT.md', 'r') as f:
    text = f.read()

rules = []
rule_id = 0
lines = text.split('\n')
total_lines = len(lines)
rule_pattern = re.compile(r'\*\*规则([A-Z](?:\.[0-9]+)?(?:[A-Z])?)\s*[—–-]+\s*(.+?)\*\*')

for i, line in enumerate(lines):
    m = rule_pattern.search(line)
    if m:
        rule_code = m.group(1)
        rule_desc = m.group(2)
        
        context = ''
        j = i
        while j < min(i + 30, total_lines):
            context += lines[j] + '\n'
            j += 1
            if j >= total_lines or (lines[j].startswith('**规则') and j > i):
                break
        
        priority = 'normal'
        if '最高优先级' in context or '优先级高于所有' in context:
            priority = 'highest'
        elif '优先级' in context and '高于' in context:
            priority = 'high'
        
        depends = list(set(re.findall(r'(?:规则|Step)\s*([A-Z](?:\.[0-9]+)?)', context)))
        depends = [d for d in depends if d != rule_code]
        
        overrides = list(set(re.findall(r'(?:覆盖|覆写|替代|胜出|优先于)\s*(?:规则)?([A-Z](?:\.[0-9]+)?)', context)))
        
        forbid = re.findall(r'❌\s*(.+?)(?=\n|$)', context)
        must = re.findall(r'✅\s*(.+?)(?=\n|$)', context)
        
        rule_id += 1
        rules.append({
            'id': f'R{rule_id:03d}',
            'code': rule_code,
            'name': rule_desc,
            'line': i + 1,
            'line_range': f'L{i+1}-L{min(i+30, total_lines)}',
            'category': classify_rule(rule_code, context),
            'priority': priority,
            'condition': extract_condition(context),
            'action': {
                'forbid': forbid[:5],
                'must': must[:5],
            },
            'depends_on': depends[:10],
            'overrides': overrides[:10],
            'triggers_self_check': '自检熔断' in context or '熔断' in context,
        })

print(f"Total lines: {total_lines}")
print(f"Rules extracted: {rule_id}")

with open('/home/agent/cow/scripts/rules.json', 'w') as f:
    json.dump(rules, f, ensure_ascii=False, indent=2)

print("Written to scripts/rules.json")
