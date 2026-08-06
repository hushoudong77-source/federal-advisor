#!/usr/bin/env python3
"""
外部模型审计桥接脚本 — External Auditor Bridge
将法典全文发送给外部模型（KIMI K2.6/Claude/Gemini/OpenAI）进行独立审计，
与联邦投顾自我审计结果对撞。
"""

import os
import sys
import json
import argparse

# ============================================================
# 配置
# ============================================================
AGENT_PATH = os.path.expanduser("/home/agent/cow/AGENT.md")

EXTERNAL_AUDITOR_SYSTEM_PROMPT = """你是一个投资法典逻辑审计官（Codex Auditor）。你的任务是找出以下投资法典中的所有逻辑缺陷，不做投资决策，只做文本审计。

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
- 策略逻辑是否内部矛盾（如「均值回归」和「趋势过滤」互斥）
- 单策略自由度（可调参数+判定条件数）是否超过5个（撒普红线）

### 第四层：覆盖完整性
- 全池标的是否都有对应路由
- 极端场景（VIX>50/涨停/跌停/停牌）是否有处置规则

### 第五层：历史债务
- 追溯「事故焊入」规则，检查事故条件是否仍然存在

### 第六层：外部对账
- 与 Weinstein阶段论/CAN SLIM/撒普R倍数/达利奥全天候 的对齐度

## 输出格式

请按以下格式输出审计报告：

```
# 法典逻辑审计报告

## 执行摘要
- 审计日期: [日期]
- 法典版本: [从AGENT.md提取]
- 缺陷总数: X个 (致命: Y, 严重: Z, 一般: W)

## 第0层：重力位阶锁定
[缺陷列表，每个标注位置+证据]

## 第一层：形式逻辑
[缺陷列表]

## 第二层：数值一致性 + E值退化
[缺陷列表]

## 第三层：语义自洽 + 自由度极值
[缺陷列表]

## 第四层：覆盖完整性
[缺陷列表]

## 第五层：历史债务
[缺陷列表]

## 第六层：外部对账
[缺陷列表]

## 综合评级
[A/B/C/D/F]
```

只输出审计报告，不要输出任何解释性文字。"""


def load_agent_md():
    with open(AGENT_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def build_audit_prompt(codex_text):
    """构建审计提示词"""
    return f"""以下是需要审计的投资法典全文（AGENT.md，已截断至前50000字符以适应上下文限制）。请按照你的审计框架逐层分析。

=== 法典开始 ===
{codex_text[:50000]}
=== 法典结束 ===

请输出完整的六层审计报告。"""


def audit_with_claude(codex_text):
    """使用 Claude API 进行审计"""
    api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "CLAUDE_API_KEY 未配置"}

    import requests
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 8000,
            "system": EXTERNAL_AUDITOR_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_audit_prompt(codex_text)}],
        },
        timeout=120
    )

    if response.status_code == 200:
        data = response.json()
        return {"success": True, "model": "claude", "content": data["content"][0]["text"]}
    else:
        return {"error": f"Claude API 错误: {response.status_code} {response.text[:200]}"}


def audit_with_openai(codex_text):
    """使用 OpenAI API 进行审计"""
    api_key = os.environ.get("OPENAI_API_KEY")
    api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    if not api_key:
        return {"error": "OPENAI_API_KEY 未配置"}

    import requests
    response = requests.post(
        f"{api_base}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": EXTERNAL_AUDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": build_audit_prompt(codex_text)},
            ],
            "max_tokens": 8000,
        },
        timeout=120
    )

    if response.status_code == 200:
        data = response.json()
        return {"success": True, "model": "openai", "content": data["choices"][0]["message"]["content"]}
    else:
        return {"error": f"OpenAI API 错误: {response.status_code} {response.text[:200]}"}


def audit_with_gemini(codex_text):
    """使用 Gemini API 进行审计"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY 未配置"}

    import requests
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": EXTERNAL_AUDITOR_SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": build_audit_prompt(codex_text)}]}],
        },
        timeout=120
    )

    if response.status_code == 200:
        data = response.json()
        return {"success": True, "model": "gemini", "content": data["candidates"][0]["content"]["parts"][0]["text"]}
    else:
        return {"error": f"Gemini API 错误: {response.status_code} {response.text[:200]}"}


def audit_with_kimi(codex_text):
    """
    使用 KIMI K2.6 API 进行审计（兼容 OpenAI 格式）
    K2.6 是 Kimi 最新最智能模型，支持 256K 上下文。
    K2.6 默认启用 thinking 模式（不可禁用），无需显式传参。
    如需保留历史思考（多轮审计场景），可传 extra_body={"thinking": {"type": "enabled", "keep": "all"}}。
    实测：47缺陷/23严重，综合评级D，远超 moonshot-v1（4缺陷）和 K2.5（15缺陷）。
    """
    api_key = os.environ.get("KIMI_API_KEY")
    if not api_key:
        return {"error": "KIMI_API_KEY 未配置"}

    import requests

    # K2.6 256K 上下文，吃完整法典
    max_chars = 100000
    truncated = codex_text[:max_chars]

    audit_prompt = f"""以下是需要审计的投资法典全文（AGENT.md）。请按照你的审计框架逐层分析。

=== 法典开始 ===
{truncated}
=== 法典结束 ===

请输出完整的六层审计报告。每个缺陷必须标注具体位置（模块名/条款编号）。"""

    response = requests.post(
        "https://api.moonshot.cn/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "kimi-k2.6",
            "messages": [
                {"role": "system", "content": EXTERNAL_AUDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": audit_prompt},
            ],
            "max_tokens": 16000,  # 官方建议≥16000
            # K2.6 默认启用 thinking，无需 extra_body
        },
        timeout=900
    )

    if response.status_code == 200:
        data = response.json()
        msg = data["choices"][0].get("message", {})
        content = msg.get("content", "")

        if not content:
            return {"error": "KIMI K2.6 返回空内容"}

        return {"success": True, "model": "kimi-k2.6", "content": content}
    else:
        return {"error": f"KIMI API 错误: {response.status_code} {response.text[:300]}"}


def main():
    parser = argparse.ArgumentParser(description="外部模型审计桥接")
    parser.add_argument("--model", choices=["claude", "openai", "gemini", "kimi"], default="kimi",
                        help="使用的外部模型 (default: kimi)")
    parser.add_argument("--source", default=AGENT_PATH,
                        help="法典文件路径 (default: AGENT.md)")
    parser.add_argument("--output", default=None,
                        help="审计报告输出路径 (默认打印到stdout)")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"❌ 错误: 源文件不存在: {args.source}")
        sys.exit(1)

    codex_text = load_agent_md() if args.source == AGENT_PATH else open(args.source).read()

    print(f"🔍 外部模型审计: {args.model}")
    print(f"法典长度: {len(codex_text)} 字符")
    print(f"{'='*60}")

    auditors = {
        "claude": audit_with_claude,
        "openai": audit_with_openai,
        "gemini": audit_with_gemini,
        "kimi": audit_with_kimi,  # kimi-k2.6 (最新最智能)
    }

    result = auditors[args.model](codex_text)

    if "error" in result:
        print(f"❌ {result['error']}")
        sys.exit(1)

    print(result["content"])

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result["content"])
        print(f"\n✅ 审计报告已保存至: {args.output}")


if __name__ == "__main__":
    main()
