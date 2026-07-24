#!/usr/bin/env python3
import json

with open('/home/agent/cow/tmp/segment_audit_v1.json') as f:
    data = json.load(f)

valid = []
noise = []

for r in data:
    seg = r['segment']
    content = r.get('content', '')
    if not content:
        continue
    
    try:
        # 有些返回可能包含Markdown包裹的JSON
        clean = content
        if '```json' in clean:
            clean = clean.split('```json')[1].split('```')[0]
        elif '```' in clean:
            clean = clean.split('```')[1].split('```')[0]
        
        obj = json.loads(clean)
        for d in obj.get('defects', []):
            desc = d.get('description', '')
            layer = d.get('layer', '')
            
            # 过滤噪音
            noise_layer_prefixes = ['第L', '第十', '第十四', '第十六']
            if any(layer.startswith(p) for p in noise_layer_prefixes):
                noise.append(f"[{seg}] {layer}: {desc[:80]}")
                continue
            
            # S4/S5的严重缺陷通常是自审日志的旧bug
            if seg in ('S4_自审日志', 'S5_大师对撞回测'):
                if any(kw in desc for kw in ['回测', '仓位', '方向', '阈值', '五维', '博弈态']):
                    noise.append(f"[{seg}] [旧bug重报] {desc[:80]}")
                    continue
            
            valid.append({
                'segment': seg,
                'layer': layer,
                'severity': d.get('severity', '?'),
                'location': d.get('location', ''),
                'description': desc,
                'evidence': d.get('evidence', '')[:200],
                'fix': d.get('fix', '')
            })
    except (json.JSONDecodeError, KeyError) as e:
        print(f"WARN {seg}: JSON parse fail: {e}")
        print(content[:200])

print(f"\nValid defects: {len(valid)}")
print(f"Noise (old bugs / bad layers): {len(noise)}")
print(f"\n===== VALID DEFECTS =====")
for i, d in enumerate(valid):
    print(f"\n#{i+1} [{d['severity']}] [{d['layer']}] [{d['segment']}]")
    print(f"   Location: {d['location']}")
    print(f"   Desc: {d['description']}")
    print(f"   Evidence: {d['evidence'][:150]}")
    if d['fix']:
        print(f"   Fix: {d['fix'][:150]}")

print(f"\n===== NOISE (filtered) =====")
for n in noise[:10]:
    print(f"  {n}")
print(f"  ... total {len(noise)} noise items")
