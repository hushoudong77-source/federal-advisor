#!/usr/bin/env python3
"""
联邦法典独立审计引擎 V1.0 — Codex Auditor Core
对 AGENT.md 执行六层全量逻辑审计，输出结构化 BUG 报告。
"""

import re
import os
import sys
import json
from datetime import datetime
from collections import defaultdict

# ============================================================
# 配置
# ============================================================
AGENT_PATH = os.path.expanduser("/home/agent/cow/AGENT.md")
RULES_JSON_PATH = os.path.expanduser("/home/agent/cow/scripts/rules.json")

# ============================================================
# 审计结果数据结构
# ============================================================
class AuditFinding:
    def __init__(self, layer, code, severity, description, location="", suggestion=""):
        self.layer = layer
        self.code = code
        self.severity = severity  # 🔴严重 🟡警告 🟢建议
        self.description = description
        self.location = location
        self.suggestion = suggestion

    def __repr__(self):
        return f"[{self.severity}] L{self.layer} {self.code}: {self.description}"

class AuditReport:
    def __init__(self, source_file, version):
        self.source_file = source_file
        self.version = version
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.findings = []
        self.stats = defaultdict(int)

    def add(self, finding):
        self.findings.append(finding)
        self.stats[finding.severity] += 1

    def summary(self):
        total = len(self.findings)
        return {
            "total": total,
            "critical": self.stats.get("🔴严重", 0),
            "warning": self.stats.get("🟡警告", 0),
            "suggestion": self.stats.get("🟢建议", 0),
        }

# ============================================================
# 文本分析工具
# ============================================================
def load_agent_md(path):
    """加载 AGENT.md 全文"""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def extract_sections(text):
    """提取所有模块段落"""
    sections = {}
    # 匹配模块标题
    pattern = r'(?:###\s+)?模块\s*([零一二三四五六七八九十]+|[0-9]+)[：:]\s*(.+?)(?=\n(?:###\s+)?模块\s*(?:[零一二三四五六七八九十]+|[0-9]+)[：:]|\n##\s|\Z)'
    matches = re.findall(pattern, text, re.DOTALL)
    for num, content in matches:
        sections[f"模块{num}"] = content.strip()
    return sections

def find_all_occurrences(text, pattern, label=""):
    """查找所有匹配并返回位置信息"""
    results = []
    for m in re.finditer(pattern, text, re.MULTILINE):
        line_num = text[:m.start()].count('\n') + 1
        results.append({"match": m.group(), "line": line_num, "label": label})
    return results

# ============================================================
# 第 0 层：重力位阶锁定审计
# ============================================================
def audit_layer0_gravity(text, report):
    """审查规则是否违背物理重力 > 趋势 > 价值的位阶"""
    
    # 检查是否有规则试图绕过 IEF 熔断
    ief_bypass_patterns = [
        (r'IEF\s*[<>]\s*95', "IEF阈值引用", "确认是否被正确用作熔断而非建议"),
    ]
    
    for pattern, label, desc in ief_bypass_patterns:
        matches = find_all_occurrences(text, pattern, label)
        # 检查上下文是否将IEF作为建议而非熔断
        for m in matches:
            context_start = max(0, text.rfind('\n', 0, m['match'].find('IEF') if 'IEF' in m['match'] else 0) - 200)
            context = text[context_start:m['match'].find('IEF') + 100] if 'IEF' in m['match'] else ""
            if "建议" in context and "熔断" not in context:
                report.add(AuditFinding(
                    layer=0, code="GRAV-001",
                    severity="🔴严重",
                    description=f"IEF阈值被用作建议而非熔断: {m['match'][:80]}",
                    location=f"L{m['line']}",
                    suggestion="IEF<95.00必须是硬熔断，不可降级为建议"
                ))
    
    # 检查是否有「价值分析」置于「物理数据」之上的表述
    value_first_patterns = [
        r'基本面.*优于.*技术',
        r'估值.*决定.*操作',
        r'价值.*优先.*物理',
    ]
    for pat in value_first_patterns:
        matches = find_all_occurrences(text, pat, "位阶反转")
        for m in matches:
            report.add(AuditFinding(
                layer=0, code="GRAV-002",
                severity="🔴严重",
                description=f"可能存在价值分析优先于物理数据的表述: {m['match'][:80]}",
                location=f"L{m['line']}",
                suggestion="物理数据对撞必须优先于价值分析"
            ))

# ============================================================
# 第一层：形式逻辑审计（调用 rule_conflict_checker.py）
# ============================================================
def audit_layer1_formal_logic(report):
    """运行规则冲突检测引擎"""
    checker_path = os.path.expanduser("/home/agent/cow/scripts/rule_conflict_checker.py")
    
    if not os.path.exists(checker_path):
        report.add(AuditFinding(
            layer=1, code="FORM-001",
            severity="🟡警告",
            description="rule_conflict_checker.py 不存在，跳过自动形式逻辑检测",
            suggestion="运行 /home/agent/cow/scripts/rule_conflict_checker.py 进行形式逻辑检测"
        ))
        return
    
    import subprocess
    try:
        result = subprocess.run(
            ["python3", checker_path],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr
        
        # 解析输出中的冲突检测结果
        conflict_patterns = [
            (r'循环依赖.*?(\d+)', "循环依赖"),
            (r'互相覆盖.*?(\d+)', "互相覆盖"),
            (r'动作互斥.*?(\d+)', "动作互斥"),
            (r'优先级[链脱].*?(\d+)', "优先级链断裂"),
            (r'悬浮引用.*?(\d+)', "悬浮引用"),
            (r'僵尸规则.*?(\d+)', "僵尸规则"),
        ]
        
        found_any = False
        for pat, ctype in conflict_patterns:
            matches = re.findall(pat, output)
            if matches:
                found_any = True
                report.add(AuditFinding(
                    layer=1, code=f"FORM-{len(report.findings)+1:03d}",
                    severity="🔴严重" if "循环" in ctype or "互斥" in ctype else "🟡警告",
                    description=f"形式逻辑冲突: {ctype} ({len(matches)}处)",
                    suggestion=f"查看 rule_conflict_checker.py 输出详情"
                ))
        
        if not found_any:
            report.add(AuditFinding(
                layer=1, code="FORM-PASS",
                severity="🟢建议",
                description="规则冲突检测引擎运行完成，未发现形式逻辑冲突",
            ))
    except Exception as e:
        report.add(AuditFinding(
            layer=1, code="FORM-ERR",
            severity="🟡警告",
            description=f"规则冲突检测引擎运行失败: {str(e)}",
        ))

# ============================================================
# 第二层：数值一致性 + E值退化审计
# ============================================================
def audit_layer2_numerical(text, report):
    """检查参数一致性 + E值退化"""
    
    # 检查关键参数是否在不同位置一致
    param_checks = [
        # (参数名, 正则模式列表, 期望一致性)
        ("ATR乘数(反击默认)", [r'(\d+\.?\d*)\s*[×xX]\s*ATR', r'k\s*=\s*(\d+\.?\d*)'], "2.0"),
        ("冷却期(反击默认)", [r'冷却期[：:]?\s*(\d+)\s*天'], "30"),
        ("单笔仓位(进攻)", [r'单笔\s*(\d+)%'], "10"),
        ("SRC-6硬止损", [r'SRC-6.*?[-−](\d+)%', r'硬止损.*?[-−](\d+)%'], "15"),
    ]
    
    for param_name, patterns, expected in param_checks:
        values = set()
        for pat in patterns:
            matches = re.findall(pat, text)
            for m in matches:
                values.add(m)
        if len(values) > 1 and expected not in values:
            report.add(AuditFinding(
                layer=2, code="NUM-001",
                severity="🟡警告",
                description=f"参数不一致: {param_name} — 发现值: {values}, 期望: {expected}",
                suggestion=f"统一 {param_name} 为 {expected}"
            ))
    
    # E值退化审计 — 检查是否有模糊止损表述
    fuzzy_stop_patterns = [
        r'看情况.*卖',
        r'酌情.*止损',
        r'灵活.*处理',
        r'视情况.*离场',
        r'根据市场.*决定',
    ]
    for pat in fuzzy_stop_patterns:
        matches = find_all_occurrences(text, pat, "模糊止损")
        for m in matches:
            report.add(AuditFinding(
                layer=2, code="EVAL-001",
                severity="🔴严重",
                description=f"E值退化: 发现模糊止损表述 — {m['match'][:60]}",
                location=f"L{m['line']}",
                suggestion="止损必须可量化，R值不可控=逻辑坍塌。改为具体数值或条件。"
            ))

# ============================================================
# 第三层：语义自洽 + 自由度极值审计
# ============================================================
def audit_layer3_semantic(text, report):
    """检查策略逻辑内部矛盾 + 自由度统计"""
    
    # 语义矛盾检测
    contradictions = [
        ("均值回归 vs 趋势过滤", 
         r'均值回归|counterpunch.*回归',
         r'趋势过滤|趋势跟随|MA40方向.*过滤',
         "反击策略声称均值回归但R0.5使用趋势方向过滤"),
        ("永不离场 vs 危机离场",
         r'永不离场|宪法.*永不离场',
         r'VIX\s*>\s*50.*清仓|MELTDOWN.*离场',
         "固定层声称永不离场但VIX>50时有离场条款"),
    ]
    
    for name, pat_a, pat_b, desc in contradictions:
        has_a = bool(re.search(pat_a, text))
        has_b = bool(re.search(pat_b, text))
        if has_a and has_b:
            report.add(AuditFinding(
                layer=3, code="SEM-001",
                severity="🟡警告",
                description=f"潜在语义矛盾: {name} — {desc}",
                suggestion="确认优先级: 哪个规则在冲突时胜出？"
            ))
    
    # 自由度极值审计 — 统计每个标的的操作条件数
    # 简化版：检查 C1/C2/C3/C4 叠加
    condition_count = len(re.findall(r'C\d[：:.]', text))
    if condition_count > 20:  # 全池合计
        report.add(AuditFinding(
            layer=3, code="DOF-001",
            severity="🟡警告",
            description=f"全池条件自由度较高（检测到{condition_count}个C级条件引用），建议逐策略统计是否超过5个自由度",
            suggestion="撒普红线: 单策略自由度≤5。超过则判定为过度拟合。"
        ))

# ============================================================
# 第四层：覆盖完整性审计
# ============================================================
def audit_layer4_coverage(text, report):
    """检查全池标的覆盖 + 极端场景处置"""
    
    # 全池白名单
    pool = {
        "美股": ["QQQ", "IVV", "IAU", "BBJP", "MUFG", "EWY", "VNM", "FLIN", "SMIN", "VEA", "VTI", "BOTZ"],
        "A股": ["588000", "513180", "513910", "510500", "518880", "512100", "510880", "159530"],
    }
    
    # 检查每个标的是否有路由归属
    all_codes = pool["美股"] + pool["A股"]
    for code in all_codes:
        # 搜索标的代码是否在路由相关段落中出现
        if code not in text:
            report.add(AuditFinding(
                layer=4, code="COV-001",
                severity="🔴严重",
                description=f"标的 {code} 在全池白名单中但AGENT.md中未找到引用",
                suggestion=f"确认 {code} 的路由归属和参数是否已定义"
            ))
    
    # 检查 VIX 四档状态的处置完整性
    vix_states = ["NORMAL", "ALERT", "CRISIS", "MELTDOWN"]
    for state in vix_states:
        if state not in text:
            report.add(AuditFinding(
                layer=4, code="COV-002",
                severity="🔴严重",
                description=f"VIX状态 '{state}' 未在AGENT.md中定义处置规则",
                suggestion=f"补充 {state} 状态下的全池标的处置矩阵"
            ))
    
    # 检查极端场景
    extreme_scenarios = ["停牌", "涨停", "跌停", "流动性枯竭", "交易暂停"]
    for scenario in extreme_scenarios:
        if scenario not in text:
            report.add(AuditFinding(
                layer=4, code="COV-003",
                severity="🟡警告",
                description=f"极端场景 '{scenario}' 未在AGENT.md中找到处置规则",
                suggestion=f"考虑补充 {scenario} 场景的处置SOP"
            ))

# ============================================================
# 第五层：历史债务审计
# ============================================================
def audit_layer5_historical_debt(text, report):
    """追溯事故焊入规则的当前必要性"""
    
    # 查找所有「根因」标记
    root_cause_pattern = r'🔴\s*根因[：:]\s*(.+?)(?=\n\n|\n###|\Z)'
    root_causes = re.findall(root_cause_pattern, text, re.DOTALL)
    
    for i, rc in enumerate(root_causes):
        # 提取事故日期
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', rc)
        date = date_match.group(1) if date_match else "未知"
        
        # 提取涉及的标的
        tickers = re.findall(r'[A-Z]{2,5}(?:\.[A-Z]{2})?', rc)
        tickers = [t for t in tickers if t not in ['VIX', 'ATR', 'MACD', 'RSI', 'ADX', 'EMA', 'MA', 'ETF', 'API', 'SOP', 'AND', 'OR', 'CBOE', 'DXY', 'CRB', 'CPI', 'PCE', 'FOMC', 'SHIBOR', 'USD', 'CNY', 'SPX', 'TD', 'KDJ', 'OBV']]
        
        report.add(AuditFinding(
            layer=5, code=f"DEBT-{i+1:03d}",
            severity="🟡警告",
            description=f"事故焊入规则 #{i+1}: 日期={date}, 涉及标的={tickers if tickers else '无特定标的'}",
            location=rc[:120].replace('\n', ' '),
            suggestion="检查事故条件是否仍然存在。若已消失，考虑移除或简化该规则。"
        ))

# ============================================================
# 第六层：外部对账审计
# ============================================================
def audit_layer6_external_alignment(text, report):
    """检查与业界标准框架的对齐度"""
    
    frameworks = {
        "Weinstein阶段论": {
            "keywords": ["阶段", "Stage", "30周均线", "阶段分析"],
            "expected": "MA40=~200日≈30周均线，法典应使用阶段论进行趋势定位"
        },
        "撒普R倍数": {
            "keywords": ["R倍数", "1R", "期望值", "盈亏比"],
            "expected": "所有策略的止损应可量化为1R"
        },
        "达利奥全天候": {
            "keywords": ["全天候", "风险平价", "圣杯"],
            "expected": "固定层VEA/VTI应体现风险平价思想"
        },
        "CAN SLIM": {
            "keywords": ["CAN SLIM", "CANSLIM", "当期盈利", "年度盈利"],
            "expected": "进攻策略应包含基本面过滤（当前可能缺失）"
        },
    }
    
    for fw_name, fw_info in frameworks.items():
        found = any(kw in text for kw in fw_info["keywords"])
        if not found:
            report.add(AuditFinding(
                layer=6, code="EXT-001",
                severity="🟢建议",
                description=f"外部框架 '{fw_name}' 未在法典中找到明确引用",
                suggestion=fw_info["expected"]
            ))

# ============================================================
# 死循环审计：寻找能摧毁新规则的 3 个反转场景
# ============================================================
def audit_death_loop(text, report):
    """寻找能摧毁最新规则的极端场景"""
    
    # 找到最近焊入的规则（按日期排序）
    recent_dates = re.findall(r'(\d{4}-\d{2}-\d{2})\s*(?:焊入|确权焊入|守东确权焊入)', text)
    if recent_dates:
        latest_date = max(recent_dates)
        # 查找该日期附近的规则
        idx = text.find(latest_date)
        if idx > 0:
            context = text[max(0,idx-500):idx+1000]
            # 提取规则名称
            rule_names = re.findall(r'(?:###\s*)?(?:🔴\s*)?([^#\n]{10,80}?(?:协议|规则|策略|纪律|SOP|机制)[^#\n]*)', context)
            
            if rule_names:
                report.add(AuditFinding(
                    layer="死循环", code="DEATH-001",
                    severity="🔴严重",
                    description=f"最新焊入规则 ({latest_date}): {rule_names[0][:80]}",
                    suggestion="请在以下三个反转场景中测试该规则是否仍然有效"
                ))
    
    # 三个通用反转场景模板
    death_scenarios = [
        "反转场景1: VIX从18飙升至55+US10Y从4.2%暴跌至3.5% — 流动性危机+利率下行双重冲击，是否所有止损规则仍然有效？",
        "反转场景2: 全池20标同一交易日触发12个买入信号 — 资金是否足够？仓位硬上限是否会在批量触发时被突破？",
        "反转场景3: 连续3笔止损后第4笔信号触发 — 规则A冷却期内是否有规则允许「系统认为应该买但规则说不能买」的矛盾？",
    ]
    
    for scenario in death_scenarios:
        report.add(AuditFinding(
            layer="死循环", code="DEATH-SCENARIO",
            severity="🟡警告",
            description=scenario,
        ))

# ============================================================
# 主审计流程
# ============================================================
def run_full_audit():
    """执行六层全量审计"""
    
    # 加载法典
    if not os.path.exists(AGENT_PATH):
        print(f"❌ 错误: AGENT.md 未找到于 {AGENT_PATH}")
        sys.exit(1)
    
    text = load_agent_md(AGENT_PATH)
    
    # 提取版本号
    version_match = re.search(r'V(\d+\.\d+\.\d+r\d+)', text)
    version = version_match.group(0) if version_match else "未知版本"
    
    report = AuditReport(AGENT_PATH, version)
    
    print(f"🔍 联邦法典独立审计引擎 V1.0")
    print(f"审计目标: AGENT.md ({len(text.split(chr(10)))}行, {version})")
    print(f"审计时间: {report.timestamp}")
    print(f"{'='*60}")
    
    # 逐层执行
    layers = [
        ("第0层: 重力位阶锁定", lambda: audit_layer0_gravity(text, report)),
        ("第1层: 形式逻辑", lambda: audit_layer1_formal_logic(report)),
        ("第2层: 数值一致性+E值退化", lambda: audit_layer2_numerical(text, report)),
        ("第3层: 语义自洽+自由度极值", lambda: audit_layer3_semantic(text, report)),
        ("第4层: 覆盖完整性", lambda: audit_layer4_coverage(text, report)),
        ("第5层: 历史债务", lambda: audit_layer5_historical_debt(text, report)),
        ("第6层: 外部对账", lambda: audit_layer6_external_alignment(text, report)),
    ]
    
    for layer_name, audit_fn in layers:
        print(f"\n{'─'*40}")
        print(f"执行 {layer_name}...")
        try:
            audit_fn()
            layer_findings = [f for f in report.findings if f.layer == int(layer_name[1]) if isinstance(f.layer, int) or (isinstance(f.layer, str) and f.layer == layer_name[1])]
            if not any(f for f in report.findings if (isinstance(f.layer, int) and f.layer == int(layer_name[1])) or (isinstance(f.layer, str) and f.layer == layer_name[1])):
                print(f"  ✅ 通过 — 未发现缺陷")
            else:
                for f in report.findings:
                    if (isinstance(f.layer, int) and f.layer == int(layer_name[1])) or (isinstance(f.layer, str) and f.layer == layer_name[1]):
                        print(f"  {f.severity} {f.code}: {f.description[:100]}")
        except Exception as e:
            print(f"  ❌ 执行失败: {str(e)}")
            report.add(AuditFinding(
                layer=int(layer_name[1]),
                code="SYS-ERR",
                severity="🟡警告",
                description=f"{layer_name} 执行异常: {str(e)}"
            ))
    
    # 死循环审计
    print(f"\n{'─'*40}")
    print(f"执行 死循环审计...")
    audit_death_loop(text, report)
    
    # 汇总
    print(f"\n{'='*60}")
    print(f"📊 审计完成")
    s = report.summary()
    print(f"总缺陷数: {s['total']}")
    print(f"  🔴严重: {s['critical']}")
    print(f"  🟡警告: {s['warning']}")
    print(f"  🟢建议: {s['suggestion']}")
    
    # 评级
    if s['critical'] == 0 and s['warning'] <= 3:
        grade = "A"
    elif s['critical'] == 0:
        grade = "B"
    elif s['critical'] <= 3:
        grade = "C"
    elif s['critical'] <= 10:
        grade = "D"
    else:
        grade = "F"
    
    print(f"综合评级: {grade}")
    
    return report

if __name__ == "__main__":
    run_full_audit()
