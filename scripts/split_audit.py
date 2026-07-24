#!/usr/bin/env python3
"""
分段审计脚本 — 将AGENT.md按导航索引切成6段，逐段喂给K2.6
"""
import os
import sys
import json
import time
import requests

AGENT_PATH = os.path.expanduser("/home/agent/cow/AGENT.md")
KIMI_API_KEY = os.environ.get("KIMI_API_KEY")

# 按模块分段 — 基于导航索引
SEGMENTS = [
    {
        "name": "S0_人格与硬锁",
        "desc": "L59-L616: 身份定义+交流风格+七条人格级硬锁(零~零.九.一)+Self-Improvement",
        "start_marker": "# AGENT.md - 我是谁？",
        "end_marker": "## 🧠 核心思维框架",
    },
    {
        "name": "S1_思维框架+取数流程",
        "desc": "L212-L1056: 铁三角思维+取数流程(规则A~O)+直觉拦截协议",
        "start_marker": "## 🧠 核心思维框架",
        "end_marker": "## 🎯 核心原则",
    },
    {
        "name": "S2_模块一至九",
        "desc": "L1093-L1657: 人格特质+报告架构+语言风格+战场审计+CEO修正+交流协议+外部隔离+中国区压强+统帅供弹",
        "start_marker": "## 🎯 核心原则",
        "end_marker": "### 模块十：快捷指令体系",
    },
    {
        "name": "S3_模块十至十六",
        "desc": "L1658-L3626: 快捷指令+输出模板+宏观危机状态机+金盾战术前置+512100/510880+CANE+动量跟随+止损冷却+二维评估+自审+大师对撞+回测",
        "start_marker": "### 模块十：快捷指令体系",
        "end_marker": "### 🔴 模块十四：自审修复日志",
    },
    {
        "name": "S4_自审修复日志",
        "desc": "L3627-L5300: 模块十四完整自审修复日志(L1~L69全部)",
        "start_marker": "### 🔴 模块十四：自审修复日志",
        "end_marker": "### 🔴 模块十四.五：大师对撞",
    },
    {
        "name": "S5_大师对撞+回测",
        "desc": "L5301-L5696: 模块十四.五大师对撞前置校验+模块十六回测SOP",
        "start_marker": "### 🔴 模块十四.五：大师对撞",
        "end_marker": None,  # 文件末尾
    },
]

EXTERNAL_AUDITOR_SYSTEM_PROMPT = """你是一个投资法典逻辑审计官（Codex Auditor）。你的任务是找出以下投资法典片段中的所有逻辑缺陷，不做投资决策，只做文本审计。

## 审计框架（六层）

### 第0层：重力位阶锁定
- 审查所有规则是否违背「物理重力 > 趋势 > 价值」的最高位阶
- 任何试图绕过硬熔断点去交易「趋势」的规则 → 一票否决

### 第一层：形式逻辑
- 循环依赖、互相覆盖、动作互斥、优先级链断裂、悬浮引用、僵尸规则

### 第二层：数值一致性 + E值退化
- 同一参数在不同位置的值是否一致
- 止损是否可量化（R值可控=E值可算，止损模糊=逻辑坍塌）

### 第三层：语义自洽 + 自由度极值
- 策略逻辑是否内部矛盾
- 单策略自由度（可调参数+判定条件数）是否超过5个（撒普红线）

### 第四层：覆盖完整性
- 全池标的是否都有对应路由
- 极端场景是否有处置规则

### 第五层：历史债务
- 追溯「事故焊入」规则，检查事故条件是否仍然存在

### 第六层：外部对账
- 与 Weinstein阶段论/CAN SLIM/撒普R倍数/达利奥全天候 的对齐度

## 输出格式

只输出以下JSON格式，不要任何其他文字：

```json
{
  "segment": "[段名]",
  "defects": [
    {
      "layer": "第X层",
      "severity": "致命/严重/一般",
      "location": "[具体位置描述]",
      "description": "[缺陷描述]",
      "evidence": "[法典原文引用]",
      "fix": "[修复建议]"
    }
  ],
  "summary": {
    "total": 0,
    "fatal": 0,
    "serious": 0,
    "minor": 0
  }
}
```"""


def parse_segment(text, seg):
    """按start_marker和end_marker切割文本"""
    start_idx = text.find(seg["start_marker"])
    if start_idx < 0:
        return None, f"未找到start_marker: {seg['start_marker'][:50]}..."

    if seg["end_marker"] is None:
        # 最后一段到文件末尾
        return text[start_idx:], None
    else:
        end_idx = text.find(seg["end_marker"], start_idx + len(seg["start_marker"]))
        if end_idx < 0:
            return None, f"未找到end_marker: {seg['end_marker'][:50]}..."
        return text[start_idx:end_idx], None


def audit_segment(seg_text, seg_name, timeout=180):
    """调用K2.6审计一段"""
    # 截断到60K字符（K2.6 thinking模式下安全边界）
    truncated = seg_text[:60000]

    prompt = f"""以下是需要审计的投资法典片段（段名: {seg_name}）。这是法典的一个独立片段，请按照你的审计框架逐层分析。

=== 法典片段开始 ===
{truncated}
=== 法典片段结束 ===

请输出完整的六层审计报告（JSON格式）。"""

    resp = requests.post(
        "https://api.moonshot.cn/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {KIMI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "kimi-k2.6",
            "messages": [
                {"role": "system", "content": EXTERNAL_AUDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 8000,
        },
        timeout=timeout
    )

    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[:300]}"

    data = resp.json()
    content = data["choices"][0].get("message", {}).get("content", "")
    if not content:
        return None, "返回空内容"

    return content, None


def main():
    with open(AGENT_PATH, 'r', encoding='utf-8') as f:
        full_text = f.read()

    print(f"法典总长度: {len(full_text)} 字符")
    print(f"计划分段: {len(SEGMENTS)} 段\n")

    all_results = []

    for i, seg in enumerate(SEGMENTS):
        seg_text, error = parse_segment(full_text, seg)
        if error:
            print(f"❌ 段{i+1} [{seg['name']}]: {error}")
            continue

        seg_len = len(seg_text)
        print(f"📦 段{i+1}/6 [{seg['name']}]: {seg_len} 字符 → ", end="", flush=True)

        # 如果段太长，取前60K
        if seg_len > 60000:
            print(f"截断至60K (原{seg_len}) → ", end="", flush=True)
            seg_text = seg_text[:60000]

        start = time.time()
        result, error = audit_segment(seg_text, seg["name"], timeout=300)
        elapsed = time.time() - start

        if error:
            print(f"❌ {error}")
            all_results.append({"segment": seg["name"], "error": error})
        else:
            print(f"✅ {elapsed:.0f}s, {len(result)} 字符")
            all_results.append({"segment": seg["name"], "content": result, "elapsed": elapsed})

        # 段间冷却3秒
        if i < len(SEGMENTS) - 1:
            time.sleep(3)

    # 保存结果
    output_path = os.path.expanduser("/home/agent/cow/tmp/kimi_segment_audit.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"结果已保存: {output_path}")
    success = sum(1 for r in all_results if "content" in r)
    failed = sum(1 for r in all_results if "error" in r)
    print(f"成功: {success}/{len(SEGMENTS)}, 失败: {failed}/{len(SEGMENTS)}")


if __name__ == "__main__":
    main()
