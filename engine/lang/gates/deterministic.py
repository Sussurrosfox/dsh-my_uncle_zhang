# -*- coding: utf-8 -*-
"""
lang.gates.deterministic
------------------------
确定性门禁检查函数集合（代码可判定逻辑，无需 LLM 猜测）。
对应 to_lang.md §4.2 与 to_upgrade.md §11.2 的各门禁规则。
"""

from __future__ import annotations
import re
from typing import Any
from collections import defaultdict, deque
from lang.state import GraphState


class CheckFailures(list):
    """同时兼容 list[dict] 和 CheckResult.passed / failures 接口"""
    @property
    def passed(self) -> bool:
        return len(self) == 0

    @property
    def failures(self) -> list:
        return list(self)

    @property
    def decision(self) -> str:
        return "pass" if len(self) == 0 else "fail"


# 版本门禁要求的内容 gate（version_gate 自身除外）
REQUIRED_GATES = [
    "source_gate",
    "diagnosis_gate",
    "dependency_gate",
    "pedagogy_gate",
    "feedback_gate",
    "student_trial_gate",
    "output_gate",
]


# =========================================================================
# 1. 来源门禁 (source_gate) 检查
# =========================================================================

def check_all_sources_verified(state: GraphState) -> CheckFailures:
    """所有 source_node 的 transcription_status 必须为 verified。"""
    failures = []
    if not state.sources:
        failures.append({
            "check": "check_all_sources_verified",
            "target": "sources",
            "route_to": "uncertain_transcription",
            "msg": "来源证据包为空，未录入任何 source_node",
            "severity": "P0_stop"
        })
        return CheckFailures(failures)

    for s in state.sources:
        if s.transcription_status != "verified":
            failures.append({
                "check": "check_all_sources_verified",
                "target": s.source_id,
                "route_to": "uncertain_transcription",
                "msg": f"来源 {s.source_id} 状态为 '{s.transcription_status}'，尚未完成 verified 认证",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_high_risk_reviewed(state: GraphState) -> CheckFailures:
    """高风险对象（公式/符号/图/ risk != none）必须 100% 具备非空 reviewer。"""
    failures = []
    for s in state.sources:
        if s.risk != "none" and not s.reviewer.strip():
            failures.append({
                "check": "check_high_risk_reviewed",
                "target": s.source_id,
                "route_to": "missing_reviewer",
                "msg": f"高风险条目 {s.source_id} (risk={s.risk}) 缺少责任审核人签署",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_risks_have_actions(state: GraphState) -> CheckFailures:
    """标记了 risk 的条目必须具备明确的处置记录（reviewed_at 非空）。"""
    failures = []
    for s in state.sources:
        if s.risk != "none" and not s.reviewed_at.strip():
            failures.append({
                "check": "check_risks_have_actions",
                "target": s.source_id,
                "route_to": "unhandled_risk",
                "msg": f"风险条目 {s.source_id} 尚未登记处理时间戳 (reviewed_at 为空)",
                "severity": "P1"
            })
    return CheckFailures(failures)


# =========================================================================
# 2. 诊断门禁 (diagnosis_gate) 检查
# =========================================================================

def check_diagnoses_non_empty(state: GraphState) -> CheckFailures:
    """独立阅读审计记录不能为空。"""
    if not state.diagnoses:
        return CheckFailures([{
            "check": "check_diagnoses_non_empty",
            "target": "diagnoses",
            "route_to": "missing_evidence",
            "msg": "防自学诊断记录列表为空，尚未进行独立阅读审计",
            "severity": "P1"
        }])
    return CheckFailures([])


def check_diagnosis_evidence_and_scope(state: GraphState) -> CheckFailures:
    """每条诊断记录必须包含具体的试读实录 evidence 与修复归属 fix_scope。"""
    failures = []
    for d in state.diagnoses:
        if not d.evidence or len(d.evidence.strip()) < 5:
            failures.append({
                "check": "check_diagnosis_evidence_and_scope",
                "target": d.record_id,
                "route_to": "missing_evidence",
                "msg": f"诊断记录 {d.record_id} 缺少具体试读者证据实录 (evidence 缺失或过短)",
                "severity": "P1"
            })
        if not d.fix_scope or d.fix_scope not in ("正文", "下游互动系统"):
            failures.append({
                "check": "check_diagnosis_evidence_and_scope",
                "target": d.record_id,
                "route_to": "missing_scope",
                "msg": f"诊断记录 {d.record_id} 修复归属 fix_scope 不合法: '{d.fix_scope}'",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_no_vague_reasons(state: GraphState) -> CheckFailures:
    """诊断中禁止仅写抽象模糊套话如“学生不理解”。"""
    vague_phrases = ["学生不理解", "不明白", "看不懂", "不会做", "太难了"]
    failures = []
    for d in state.diagnoses:
        ev = d.evidence.strip()
        for phrase in vague_phrases:
            if ev == phrase:
                failures.append({
                    "check": "check_no_vague_reasons",
                    "target": d.record_id,
                    "route_to": "vague_reason",
                    "msg": f"诊断记录 {d.record_id} 的 evidence 为空洞表述 '{phrase}'，缺少可观测行为细节",
                    "severity": "P1"
                })
                break
    return CheckFailures(failures)


# =========================================================================
# 3. 依赖门禁 (dependency_gate) 纯图算法检查
# =========================================================================

def check_graph_acyclic(state: GraphState) -> CheckFailures:
    """检测依赖网络是否存在环路（Kahn 拓扑排序算法）。"""
    failures = []
    node_ids = {n.node_id for n in state.nodes}
    in_degree = defaultdict(int)
    adj = defaultdict(list)

    for edge in state.edges:
        if edge.from_id in node_ids and edge.to_id in node_ids:
            adj[edge.from_id].append(edge.to_id)
            in_degree[edge.to_id] += 1
            if edge.from_id not in in_degree:
                in_degree[edge.from_id] = 0

    queue = deque([nid for nid in node_ids if in_degree[nid] == 0])
    visited_count = 0

    while queue:
        curr = queue.popleft()
        visited_count += 1
        for nxt in adj[curr]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if visited_count < len(node_ids) and len(node_ids) > 0 and len(state.edges) > 0:
        # 存在循环依赖
        failures.append({
            "check": "check_graph_acyclic",
            "target": "dependency_graph",
            "route_to": "cycle_detected",
            "msg": f"依赖网络中检测到循环依赖（拓扑排序节点数 {visited_count} < 节点总数 {len(node_ids)}）",
            "severity": "P0_stop"
        })
    return CheckFailures(failures)


def check_dependencies_closure(state: GraphState) -> CheckFailures:
    """
    按单元正文阅读次序做依赖闭合拓扑检查：
    对于每条 from_id -> to_id 边，from_id 的首次出现必须严格先于或等于 to_id。
    """
    failures = []
    # 建立单元顺序索引
    unit_order = {u.unit_id: idx for idx, u in enumerate(state.units)}
    node_map = {n.node_id: n for n in state.nodes}

    for edge in state.edges:
        from_node = node_map.get(edge.from_id)
        to_node = node_map.get(edge.to_id)

        if not from_node:
            failures.append({
                "check": "check_dependencies_closure",
                "target": edge.from_id,
                "route_to": "unclosed_dependency",
                "msg": f"依赖前置节点 {edge.from_id} 在节点库中不存在 (引用于关系: {edge.relation})",
                "severity": "P0_stop"
            })
            continue

        if not to_node:
            failures.append({
                "check": "check_dependencies_closure",
                "target": edge.to_id,
                "route_to": "unclosed_dependency",
                "msg": f"依赖目标节点 {edge.to_id} 在节点库中不存在 (引用于关系: {edge.relation})",
                "severity": "P0_stop"
            })
            continue

        # 检查首次使用先后顺序
        from_unit_idx = unit_order.get(from_node.first_use, 9999)
        to_unit_idx = unit_order.get(to_node.first_use, 9999)

        if from_unit_idx > to_unit_idx:
            failures.append({
                "check": "check_dependencies_closure",
                "target": f"{edge.from_id}->{edge.to_id}",
                "route_to": "unclosed_dependency",
                "msg": f"前置依赖未闭合: 节点 '{to_node.node_id}'(单元 {to_node.first_use}) 依赖尚未被介绍的 '{from_node.node_id}'(单元 {from_node.first_use})",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_no_dangling_references(state: GraphState) -> CheckFailures:
    """检查 units 和 tasks 中引用的 node_refs 与 prerequisite_refs 是否全部存在。"""
    failures = []
    known_nodes = {n.node_id for n in state.nodes}

    for u in state.units:
        for ref in u.node_refs:
            if ref not in known_nodes:
                failures.append({
                    "check": "check_no_dangling_references",
                    "target": u.unit_id,
                    "route_to": "dangling_reference",
                    "msg": f"单元 {u.unit_id} 引用了未定义的节点: '{ref}'",
                    "severity": "P1"
                })
    return CheckFailures(failures)


# =========================================================================
# 4. 教学门禁 (pedagogy_gate) 检查
# =========================================================================

REQUIRED_SECTIONS = [
    "进入情境", "明确目标", "前置准备", "引导观察",
    "概念命名与定义", "性质与理由", "完整示例",
    "支架练习", "边界与反例", "迁移任务", "自检与桥接"
]

OBSERVABLE_VERBS = [
    "指出", "判断", "判定", "计算", "求解", "写出",
    "证明", "构建", "构造", "比较", "分类", "诊断",
    "列出", "推导", "验证", "区分"
]


def check_minimal_unit_sections(state: GraphState) -> CheckFailures:
    """每个 unit 必须具备 §8.1 最小结构的 11 个必备区段（在 good_md 中存在标题对应）。"""
    failures = []
    if not state.good_md.strip():
        return CheckFailures([{
            "check": "check_minimal_unit_sections",
            "target": "good_md",
            "route_to": "missing_sections",
            "msg": "good.md 正文为空，尚未撰写",
            "severity": "P1"
        }])

    text = state.good_md
    for sec in REQUIRED_SECTIONS:
        # 正则检查是否包含该区段标题，如 "## 1. 进入情境" 或 "**进入情境**" 等
        pattern = re.compile(rf"(?:#+\s*.*{sec}|[*_]{{2}}.*{sec}.*[*_]{{2}}|【{sec}】)")
        if not pattern.search(text):
            failures.append({
                "check": "check_minimal_unit_sections",
                "target": sec,
                "route_to": "missing_sections",
                "msg": f"正文中缺少 §8.1 必备区段: 【{sec}】",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_observable_objectives(state: GraphState) -> CheckFailures:
    """每个 unit 的 objectives 必须包含至少一个可观察行为动词。"""
    failures = []
    for u in state.units:
        if not u.objectives:
            failures.append({
                "check": "check_observable_objectives",
                "target": u.unit_id,
                "route_to": "unobservable_objectives",
                "msg": f"单元 {u.unit_id} 缺少目标描述 (objectives 为空)",
                "severity": "P1"
            })
            continue

        for obj in u.objectives:
            has_verb = any(v in obj for v in OBSERVABLE_VERBS)
            if not has_verb:
                failures.append({
                    "check": "check_observable_objectives",
                    "target": u.unit_id,
                    "route_to": "unobservable_objectives",
                    "msg": f"单元 {u.unit_id} 目标 '{obj}' 未使用可观察行为动词（建议使用: 指出/判定/计算/证明/构造等）",
                    "severity": "P1"
                })
    return CheckFailures(failures)


def check_no_obvious_step_skips(state: GraphState) -> CheckFailures:
    """检查正文及单元小节中是否包含“显然”、“容易证明”等偷懒跳步词。"""
    forbidden_words = ["显然", "容易证明", "容易看出", "不难证明", "读者自证"]
    failures = []
    texts_to_check = [state.good_md]
    for u in state.units:
        texts_to_check.extend(u.sections.values())

    for text in texts_to_check:
        for word in forbidden_words:
            if word in text:
                failures.append({
                    "check": "check_no_obvious_step_skips",
                    "target": word,
                    "route_to": "obvious_jump",
                    "msg": f"包含禁用的跳步词汇 '{word}'，违反推理可重建性原则",
                    "severity": "P1"
                })
                break
    return CheckFailures(failures)


# =========================================================================
# 5. 反馈门禁 (feedback_gate) 检查
# =========================================================================

def check_tasks_required_fields(state: GraphState) -> CheckFailures:
    """检查 Task 的必填字段：answer, worked_solution, common_errors, error_reasons, retry_task。"""
    failures = []
    if not state.tasks:
        return CheckFailures([{
            "check": "check_tasks_required_fields",
            "target": "tasks",
            "route_to": "missing_task_fields",
            "msg": "任务库 tasks 为空，未配置任何练习",
            "severity": "P1"
        }])

    for t in state.tasks:
        missing = []
        if not t.answer.strip(): missing.append("answer")
        if not t.worked_solution.strip(): missing.append("worked_solution")
        if not t.common_errors: missing.append("common_errors")
        if not t.error_reasons: missing.append("error_reasons")
        if not t.retry_task.strip(): missing.append("retry_task")

        if missing:
            failures.append({
                "check": "check_tasks_required_fields",
                "target": t.task_id,
                "route_to": "missing_task_fields",
                "msg": f"任务 {t.task_id} 缺失必填反馈字段: {', '.join(missing)}",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_layered_hints(state: GraphState) -> CheckFailures:
    """检查 Task 必须包含分层提示：hint_1, hint_2, hint_3 均非空。"""
    failures = []
    for t in state.tasks:
        if not (t.hint_1.strip() and t.hint_2.strip() and t.hint_3.strip()):
            failures.append({
                "check": "check_layered_hints",
                "target": t.task_id,
                "route_to": "insufficient_hints",
                "msg": f"任务 {t.task_id} 未配齐三层提示 (hint_1/hint_2/hint_3 存在空值)",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_expected_evidence_validity(state: GraphState) -> CheckFailures:
    """检查 expected_evidence 非空且不是“仅最终数值”等不可诊断形式。"""
    invalid_patterns = ["仅最终数值", "数值", "数字", "答案", "选A", "选B", "选C", "选D"]
    failures = []
    for t in state.tasks:
        ev = t.expected_evidence.strip()
        if not ev or ev in invalid_patterns:
            failures.append({
                "check": "check_expected_evidence_validity",
                "target": t.task_id,
                "route_to": "invalid_expected_evidence",
                "msg": f"任务 {t.task_id} 的 expected_evidence 不合格 ('{ev}')，必须说明具体可检查的中间过程",
                "severity": "P1"
            })
    return CheckFailures(failures)


# =========================================================================
# 6. 试读门禁 (student_trial_gate) 检查
# =========================================================================

def check_trial_coverage(state: GraphState) -> CheckFailures:
    """检查试读记录覆盖率：所有 units 是否都有 student_trial 记录。"""
    failures = []
    reviewed_units = {r.target for r in state.reviews if r.kind == "student_trial"}
    for u in state.units:
        if u.unit_id not in reviewed_units:
            failures.append({
                "check": "check_trial_coverage",
                "target": u.unit_id,
                "route_to": "default",
                "msg": f"单元 {u.unit_id} 缺少学生试读覆盖记录",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_no_stagnation(state: GraphState) -> CheckFailures:
    """
    检查卡点记录：
    - 若任一 persona 出现卡点，按类别路由修复（前置缺失/解释断裂/反馈不足/目标不清）。
    - 若同一卡点复现两次以上，直接升级为 P0_stop 熔断。
    """
    failures = []
    stuck_counter = defaultdict(int)

    for r in state.reviews:
        if r.kind != "student_trial":
            continue
        for sp in r.stuck_points:
            stuck_counter[sp] += 1
            # 路由分类
            route_cat = "default"
            if "前置" in sp:
                route_cat = "前置缺失"
            elif "解释" in sp or "跳步" in sp:
                route_cat = "解释断裂"
            elif "反馈" in sp or "提示" in sp:
                route_cat = "反馈不足"
            elif "目标" in sp:
                route_cat = "目标不清"

            severity = "P0_stop" if stuck_counter[sp] >= 2 else "P1"
            failures.append({
                "check": "check_no_stagnation",
                "target": r.target,
                "route_to": route_cat,
                "msg": f"试读记录发现卡点 [{sp}] (复现次数: {stuck_counter[sp]})",
                "severity": severity
            })
    return CheckFailures(failures)


def check_review_decisions(state: GraphState) -> CheckFailures:
    """若有任何试读结论为 reject 或 revise，判定为门禁未通过。"""
    failures = []
    for r in state.reviews:
        if r.kind == "student_trial" and r.decision in ("revise", "reject"):
            failures.append({
                "check": "check_review_decisions",
                "target": r.target,
                "route_to": "default",
                "msg": f"试读者 {r.reviewer} 对目标 {r.target} 给出 '{r.decision}' 判定",
                "severity": "P1"
            })
    return CheckFailures(failures)


# =========================================================================
# 7. 输出门禁 (output_gate) 检查
# =========================================================================

def check_good_md_non_empty(state: GraphState) -> CheckFailures:
    """正文必须非空且达到基础篇幅。"""
    if not state.good_md or len(state.good_md.strip()) < 100:
        return CheckFailures([{
            "check": "check_good_md_non_empty",
            "target": "good_md",
            "route_to": "default",
            "msg": "good.md 正文内容过短或为空",
            "severity": "P1"
        }])
    return CheckFailures([])


def check_formula_conservation(state: GraphState) -> CheckFailures:
    """检查正文中的数学公式定界符成对守恒（$ 与 $$）。"""
    failures = []
    text = state.good_md
    dollar_count = text.count("$")
    double_dollar_count = text.count("$$")
    # 单 $ 个数 = dollar_count - double_dollar_count * 2
    single_dollars = dollar_count - (double_dollar_count * 2)

    if single_dollars % 2 != 0:
        failures.append({
            "check": "check_formula_conservation",
            "target": "formulas",
            "route_to": "formula_drift",
            "msg": f"检测到公式行内定界符 '$' 未成对闭合 (单 $ 出现 {single_dollars} 次)",
            "severity": "P1"
        })
    if double_dollar_count % 2 != 0:
        failures.append({
            "check": "check_formula_conservation",
            "target": "formulas",
            "route_to": "formula_drift",
            "msg": f"检测到行间公式定界符 '$$' 未成对闭合 (出现 {double_dollar_count} 次)",
            "severity": "P1"
        })
    return CheckFailures(failures)


# =========================================================================
# 8. 版本门禁 (version_gate) 检查
# =========================================================================

def validate_gates_current(state, include_version_gate: bool = True) -> list[str]:
    """返回当前构建快照下的门禁有效性错误列表；空列表 = 全部有效。

    有效性定义（fail closed，三条件缺一不可）：
      1. build_id 与当前 state.build_id 一致（排除跨构建混入）
      2. state_hash 与当前内容快照一致（排除内容变更后的旧记录）
      3. 满足 1+2 的记录中，最新一条 passed=True
    """
    from lang.snapshot import compute_state_hash

    failures = []
    current = compute_state_hash(state)
    build = getattr(state, "build_id", "")
    target_gates = REQUIRED_GATES + (["version_gate"] if include_version_gate else [])
    for gate_name in target_gates:
        valid = [
            r for r in state.gate_results
            if r.gate == gate_name and r.build_id == build and r.state_hash == current
        ]
        if not valid:
            failures.append(f"{gate_name} 没有对当前构建快照的有效执行记录")
            continue
        if not valid[-1].passed:
            failures.append(
                f"{gate_name} 对当前快照的最新结果为失败: {valid[-1].failures}"
            )
    return failures


def check_all_gates_passed(state: GraphState) -> CheckFailures:
    """核验发布前全部关键阶段的门禁历史在当前快照下均通过。"""
    errs = validate_gates_current(state, include_version_gate=False)
    failures = []
    for err in errs:
        failures.append({
            "check": "check_all_gates_passed",
            "target": "version_gate",
            "route_to": "unpassed_gates",
            "msg": err,
            "severity": "P1"
        })
    return CheckFailures(failures)


def check_hash_integrity(state: GraphState) -> CheckFailures:
    """核验输出正文哈希可复算。"""
    failures = []
    if not state.good_md:
        failures.append({
            "check": "check_hash_integrity",
            "target": "manifest",
            "route_to": "hash_failure",
            "msg": "正文内容为空，无法计算有效哈希指纹",
            "severity": "P1"
        })
    return CheckFailures(failures)


def check_task_bank_export_consistency(state: GraphState) -> CheckFailures:
    """检查正文中提及的所有任务 task_id 必须存在于 tasks 任务库中。"""
    failures = []
    known_task_ids = {t.task_id for t in state.tasks}
    # 正则查找形如 task_xxx 的引用
    found_in_text = set(re.findall(r"task_[a-zA-Z0-9_]+", state.good_md))
    for tid in found_in_text:
        if tid not in known_task_ids:
            failures.append({
                "check": "check_task_bank_export_consistency",
                "target": tid,
                "route_to": "default",
                "msg": f"正文中引用的任务 '{tid}' 未在 task-bank 中登记",
                "severity": "P1"
            })
    return CheckFailures(failures)
