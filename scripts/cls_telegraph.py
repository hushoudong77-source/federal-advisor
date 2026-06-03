#!/usr/bin/env python3
"""
财联社电报 API — 基于 AKShare stock_info_global_cls 接口
调用示例：
  python3 cls_telegraph.py                    # 默认全部，最近10条
  python3 cls_telegraph.py --symbol 重点       # 只看重点电报
  python3 cls_telegraph.py --count 20          # 最近20条
  python3 cls_telegraph.py --filter 美股        # 关键词过滤
  python3 cls_telegraph.py --filter "芯片|AI|算力" --count 5
  python3 cls_telegraph.py --json              # JSON输出
"""

import akshare as ak
import argparse
import json
import sys
from datetime import datetime


def fetch_telegraph(symbol: str = "全部"):
    """拉取财联社电报原始数据"""
    try:
        df = ak.stock_info_global_cls(symbol=symbol)
        return df
    except Exception as e:
        print(f"❌ 拉取失败: {e}", file=sys.stderr)
        sys.exit(1)


def filter_by_keywords(df, keywords: str):
    """按关键词过滤（支持 | 分隔的多关键词）"""
    import re
    pattern = re.compile(keywords, re.IGNORECASE)
    mask = df['标题'].fillna('').str.contains(pattern, regex=True) | \
           df['内容'].fillna('').str.contains(pattern, regex=True)
    return df[mask]


def format_output(df, count: int = None, as_json: bool = False):
    """格式化输出"""
    if count:
        df = df.head(count)
    
    if as_json:
        records = []
        for _, row in df.iterrows():
            records.append({
                'title': str(row['标题']),
                'content': str(row['内容']),
                'date': str(row['发布日期']),
                'time': str(row['发布时间'])
            })
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return
    
    for i, (_, row) in enumerate(df.iterrows()):
        title = row['标题'] if row['标题'] and row['标题'] != 'nan' else ''
        content = row['内容'] if row['内容'] and row['内容'] != 'nan' else ''
        date = row['发布日期']
        time_str = row['发布时间']
        
        # 截断过长内容
        if len(content) > 200:
            content = content[:200] + '...'
        
        print(f"[{i+1}] {date} {time_str}")
        if title:
            print(f"    📌 {title}")
        if content and content != title:
            print(f"    {content}")
        print()


def main():
    parser = argparse.ArgumentParser(description='财联社电报查询')
    parser.add_argument('--symbol', default='全部', choices=['全部', '重点'],
                        help='电报类别（默认全部）')
    parser.add_argument('--count', type=int, default=10,
                        help='返回条数（默认10，最大300）')
    parser.add_argument('--filter', type=str, default=None,
                        help='关键词过滤，支持 | 分隔多关键词')
    parser.add_argument('--json', action='store_true',
                        help='JSON格式输出')
    args = parser.parse_args()
    
    df = fetch_telegraph(args.symbol)
    
    if args.filter:
        df = filter_by_keywords(df, args.filter)
        if len(df) == 0:
            print(f"⚠️ 没有匹配「{args.filter}」的电报")
            return
    
    format_output(df, args.count, args.json)
    
    print(f"--- 共 {len(df)} 条 (symbol={args.symbol}) ---")


if __name__ == '__main__':
    main()
