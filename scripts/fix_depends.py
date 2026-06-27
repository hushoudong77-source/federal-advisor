import json
with open('/home/agent/cow/scripts/rules.json') as f:
    rules = json.load(f)

# Build code -> id mapping
code_to_id = {r['code']: r['id'] for r in rules}

# Fix depends_on and overrides to use code (not id)
for r in rules:
    new_deps = []
    for d in r['depends_on']:
        if d in code_to_id:
            new_deps.append(d)  # keep code
        else:
            # Try to find by id
            found = None
            for r2 in rules:
                if r2['id'] == d:
                    found = r2['code']
                    break
            if found:
                new_deps.append(found)
            else:
                new_deps.append(d)  # keep as-is for reporting
    
    new_ov = []
    for o in r['overrides']:
        if o in code_to_id:
            new_ov.append(o)
        else:
            found = None
            for r2 in rules:
                if r2['id'] == o:
                    found = r2['code']
                    break
            if found:
                new_ov.append(found)
            else:
                new_ov.append(o)
    
    r['depends_on'] = new_deps
    r['overrides'] = new_ov

with open('/home/agent/cow/scripts/rules.json', 'w') as f:
    json.dump(rules, f, ensure_ascii=False, indent=2)

print("Fixed. Checking dangling refs...")

all_codes = {r['code'] for r in rules}
dangling = 0
for r in rules:
    for dep in r['depends_on']:
        if dep not in all_codes:
            print(f"  ⚠️  {r['code']} depends_on '{dep}' → NOT FOUND")
            dangling += 1
    for ov in r['overrides']:
        if ov not in all_codes:
            print(f"  ⚠️  {r['code']} overrides '{ov}' → NOT FOUND")
            dangling += 1

print(f"Total dangling: {dangling}")
