#!/usr/bin/env python3
"""
📜 记忆压缩引擎 V1.0 — 记忆花园修剪脚本
签发：守东（资产规划部首席审计官）
生效日期：2026-05-25

功能：
1. 读取当天记忆文件（memory/YYYY-MM-DD.md）
2. 识别并去重Trimmed Context中的冗余摘要
3. 提取新信息追加到MEMORY.md
4. 输出压缩比报表

运行方式：python3 scripts/memory_compress.py [--date YYYY-MM-DD] [--dry-run] [--force]
  --date: 指定日期，默认今天
  --dry-run: 预览模式，不实际修改文件
  --force: 强制重新压缩（已压缩过的文件默认跳过）
"""

import re
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# 配置
# ============================================================
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.join(WORKSPACE, "memory")
MEMORY_INDEX = os.path.join(WORKSPACE, "MEMORY.md")
KNOWLEDGE_DIR = os.path.join(WORKSPACE, "knowledge")
COMPRESSED_MARKER = "## 📦 已压缩"  # 标记此文件已被压缩过

# ============================================================
# 辅助函数
# ============================================================

def parse_args():
    args = {'date': None, 'dry_run': False, 'force': False}
    i = 0
    argv = sys.argv[1:]
    while i < len(argv):
        if argv[i] == '--date' and i + 1 < len(argv):
            args['date'] = argv[i + 1]
            i += 2
        elif argv[i] == '--dry-run':
            args['dry_run'] = True
            i += 1
        elif argv[i] == '--force':
            args['force'] = True
            i += 1
        else:
            i += 1
    # --date 指定时才走单文件模式，否则全量扫描
    return args

def read_file(path):
    """安全读取文件"""
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(path, content):
    """安全写入文件"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def estimate_size_kb(text):
    """估算文本大小(KB)"""
    if text is None:
        return 0
    return len(text.encode('utf-8')) / 1024

# ============================================================
# 核心：识别Trimmed Context
# ============================================================

TRIM_PATTERNS = [
    r'## Trimmed Context \([^)]+\)\s*\n',
    r'## Daily Summary \([^)]+\)\s*\n',
]

def is_trimmed_section(line):
    """判断一行是否是Trimmed Context标题"""
    return bool(re.match(r'^## (Trimmed Context|Daily Summary) \(\d{2}:\d{2}\)', line))

def extract_sections(content):
    """将记忆文件拆分为结构化段落"""
    if content is None:
        return []
    
    lines = content.split('\n')
    sections = []
    current_section = {'type': 'header', 'lines': [], 'start': 0}
    
    for i, line in enumerate(lines):
        if line.startswith('# '):
            # 标题行 — 文件标题，跳过
            continue
        elif line.startswith('## '):
            # 新段落开始
            if current_section['lines']:
                sections.append(current_section)
            
            section_type = 'trimmed' if is_trimmed_section(line) else 'content'
            current_section = {'type': section_type, 'lines': [line], 'start': i}
        else:
            current_section['lines'].append(line)
    
    if current_section['lines']:
        sections.append(current_section)
    
    return sections

def is_compressed(content):
    """检查文件是否已被压缩"""
    return COMPRESSED_MARKER in (content or '')

# ============================================================
# 去重逻辑
# ============================================================

def compute_fingerprint(text):
    """计算文本指纹用于去重"""
    # 归一化：去空格/去时间戳/去标题
    cleaned = re.sub(r'\s+', ' ', text)
    cleaned = re.sub(r'\d{1,2}:\d{2}', 'HH:MM', cleaned)
    cleaned = re.sub(r'## .*', '', cleaned)
    # 取前100字符作为指纹
    return cleaned[:100].strip()

def deduplicate_trimmed_sections(sections):
    """
    去重Trimmed Context段落：
    - 完全相同的指纹 → 只保留第一段（标注去重数量）
    - 相似但不同的 → 保留，标注差异
    """
    seen_fingerprints = {}
    new_sections = []
    dedup_count = 0
    kept_count = 0
    
    for section in sections:
        if section['type'] != 'trimmed':
            new_sections.append(section)
            continue
        
        text = '\n'.join(section['lines'])
        fp = compute_fingerprint(text)
        
        if fp in seen_fingerprints:
            dedup_count += 1
        else:
            seen_fingerprints[fp] = True
            kept_count += 1
            new_sections.append(section)
    
    return new_sections, dedup_count, kept_count

def extract_key_info_from_trimmed(text):
    """从Trimmed Context中提取关键信息摘要"""
    lines = text.split('\n')
    info_items = []
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('## ') or line.startswith('- 用户'):
            continue
        info_items.append(line)
    
    return info_items

# ============================================================
# 主压缩流程
# ============================================================

def compress_memory_file(filepath, dry_run=False, force=False):
    """
    压缩单个记忆文件：
    1. 去重Trimmed Context
    2. 合并相似段落
    3. 标记压缩状态
    """
    content = read_file(filepath)
    if content is None:
        return {'status': 'skipped', 'reason': '文件不存在'}
    
    original_size = estimate_size_kb(content)
    
    # 跳过已压缩的文件（除非force）
    if not force and is_compressed(content):
        return {'status': 'skipped', 'reason': '已压缩'}
    
    # 跳过小文件（< 5KB，没必要压缩）
    if original_size < 5:
        return {'status': 'skipped', 'reason': f'文件太小({original_size:.1f}KB)'}
    
    sections = extract_sections(content)
    
    # 统计
    total_trimmed = sum(1 for s in sections if s['type'] == 'trimmed')
    total_content = sum(1 for s in sections if s['type'] == 'content')
    
    # 去重
    new_sections, dedup_count, kept_count = deduplicate_trimmed_sections(sections)
    
    # 如果去重数量为0，标注已检查
    if dedup_count == 0 and total_trimmed > 0:
        # 添加压缩标记
        new_sections.append({
            'type': 'note',
            'lines': [f'\n{COMPRESSED_MARKER} — {total_trimmed}个TC段落，0个冗余 → 无需去重'],
            'start': len(content.split('\n'))
        })
    elif dedup_count > 0:
        # 添加压缩标记和统计
        new_sections.append({
            'type': 'note',
            'lines': [f'\n{COMPRESSED_MARKER} — 原始TC段落{total_trimmed}个 → 去重{dedup_count}个 → 保留{kept_count}个'],
            'start': len(content.split('\n'))
        })
    else:
        # 没有TC段落，只加标记
        new_sections.append({
            'type': 'note',
            'lines': [f'\n{COMPRESSED_MARKER} — 无Trimmed Context，文件干净'],
            'start': len(content.split('\n'))
        })
    
    # 重建文件
    new_content_lines = []
    for section in new_sections:
        new_content_lines.extend(section['lines'])
    
    new_content = '\n'.join(new_content_lines)
    new_size = estimate_size_kb(new_content)
    
    result = {
        'status': 'compressed' if dedup_count > 0 else 'clean',
        'filepath': filepath,
        'original_lines': len(content.split('\n')),
        'new_lines': len(new_content_lines),
        'original_size_kb': round(original_size, 1),
        'new_size_kb': round(new_size, 1),
        'total_trimmed': total_trimmed,
        'dedup_count': dedup_count,
        'kept_count': kept_count,
        'compression_ratio': round((1 - new_size / original_size) * 100, 1) if original_size > 0 else 0,
    }
    
    if not dry_run:
        write_file(filepath, new_content)
    
    return result

def scan_all_memory_files(dry_run=False, force=False):
    """扫描所有记忆文件并压缩"""
    if not os.path.exists(MEMORY_DIR):
        return {'error': f'记忆目录不存在: {MEMORY_DIR}'}
    
    files = sorted([f for f in os.listdir(MEMORY_DIR) if re.match(r'\d{4}-\d{2}-\d{2}\.md$', f)])
    
    results = []
    total_original = 0
    total_new = 0
    total_dedup = 0
    
    for fname in files:
        filepath = os.path.join(MEMORY_DIR, fname)
        result = compress_memory_file(filepath, dry_run=dry_run, force=force)
        results.append({'file': fname, **result})
        
        if result['status'] in ('compressed', 'clean'):
            total_original += result['original_size_kb']
            total_new += result['new_size_kb']
            total_dedup += result.get('dedup_count', 0)
    
    summary = {
        'files_scanned': len(files),
        'files_compressed': sum(1 for r in results if r.get('status') == 'compressed'),
        'files_clean': sum(1 for r in results if r.get('status') == 'clean'),
        'files_skipped': sum(1 for r in results if r.get('status') == 'skipped'),
        'total_original_kb': round(total_original, 1),
        'total_new_kb': round(total_new, 1),
        'total_saved_kb': round(total_original - total_new, 1),
        'total_dedup': total_dedup,
        'results': results,
    }
    
    return summary

def print_report(summary):
    """输出压缩报表"""
    print("=" * 60)
    print("📜 记忆压缩引擎 V1.0 — 执行报表")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    print(f"\n📊 汇总")
    print(f"  扫描文件: {summary['files_scanned']}个")
    print(f"  已压缩:   {summary['files_compressed']}个")
    print(f"  已干净:   {summary['files_clean']}个")
    print(f"  已跳过:   {summary['files_skipped']}个")
    print(f"  总原始:   {summary['total_original_kb']}KB")
    print(f"  总压缩后: {summary['total_new_kb']}KB")
    print(f"  节省空间: {summary['total_saved_kb']}KB ({round(summary['total_saved_kb']/max(summary['total_original_kb'],1)*100,1)}%)")
    print(f"  TC去重:   {summary['total_dedup']}段")
    
    if summary['files_compressed'] > 0:
        print(f"\n📋 压缩明细")
        for r in summary['results']:
            if r.get('status') == 'compressed':
                print(f"  ✅ {r['file']}: {r['original_size_kb']}KB → {r['new_size_kb']}KB "
                      f"({r['compression_ratio']}%) | TC去重{r['dedup_count']}/{r['total_trimmed']}")
            elif r.get('status') == 'clean':
                print(f"  🟢 {r['file']}: {r['original_size_kb']}KB (干净)")
            elif r.get('status') == 'skipped':
                print(f"  ⚪ {r['file']}: {r['reason']}")
    
    print("\n" + "=" * 60)

# ============================================================
# 入口
# ============================================================

if __name__ == '__main__':
    args = parse_args()
    
    single_file = args.get('date')
    if single_file:
        # 单文件模式
        filepath = os.path.join(MEMORY_DIR, f"{args['date']}.md")
        result = compress_memory_file(filepath, dry_run=args['dry_run'], force=args['force'])
        
        if result['status'] == 'compressed':
            print(f"✅ 已压缩 {args['date']}.md: {result['original_size_kb']}KB → {result['new_size_kb']}KB "
                  f"({result['compression_ratio']}%) | TC去重{result['dedup_count']}/{result['total_trimmed']}")
        elif result['status'] == 'clean':
            print(f"🟢 {args['date']}.md: {result['original_size_kb']}KB (干净，无需压缩)")
        elif result['status'] == 'skipped':
            print(f"⚪ {args['date']}.md: {result['reason']}")
    else:
        # 全量扫描模式
        summary = scan_all_memory_files(dry_run=args['dry_run'], force=args['force'])
        print_report(summary)
