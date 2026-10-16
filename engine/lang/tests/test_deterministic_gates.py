# -*- coding: utf-8 -*-
"""
lang.tests.test_deterministic_gates
-----------------------------------
测试全部 8 个门禁的确定性纯代码校验函数 (to_lang.md §4.2, §10.2)
"""

import pytest
from lang.state import (
    GraphState, SourceNode, ConceptNode, DependencyEdge, Task,
    LearningUnit, DiagnosisRecord, ReviewRecord, GateResult, ReleaseManifest
)
from lang.gates.deterministic import (
    check_all_sources_verified,
    check_high_risk_reviewed,
    check_diagnoses_non_empty,
    check_diagnosis_evidence_and_scope,
    check_no_vague_reasons,
    check_graph_acyclic,
    check_dependencies_closure,
    check_minimal_unit_sections,
    check_no_obvious_step_skips,
    check_tasks_required_fields,
    check_layered_hints,
    check_trial_coverage,
    check_formula_conservation,
    check_all_gates_passed,
    check_hash_integrity
)


def test_gate1_source_checks():
    """测试 Gate 1: source_gate 来源校验"""
    # 场景 A: 存在未校验来源 (uncertain)
    s1 = SourceNode(
        source_id="s1",
        source_file="sample.pdf",
        page=1,
        region="1.1",
        source_quote="quote",
        transcription_status="uncertain",
        risk="none"
    )
    state_fail = GraphState(raw_files=["sample.pdf"], discipline="math", good_md_path="out.md", sources=[s1])
    failures = check_all_sources_verified(state_fail)
    assert len(failures) > 0
    assert failures[0]["route_to"] == "uncertain_transcription"

    # 场景 B: 全部已校验
    s1.transcription_status = "verified"
    state_pass = GraphState(raw_files=["sample.pdf"], discipline="math", good_md_path="out.md", sources=[s1])
    assert len(check_all_sources_verified(state_pass)) == 0


def test_gate2_diagnosis_checks():
    """测试 Gate 2: diagnosis_gate 诊断校验"""
    # 场景 A: 诊断理由空洞泛泛
    d_vague = DiagnosisRecord(
        record_id="d1",
        section_ref="1.1",
        checkpoint="goal",
        passed=False,
        labels=["vague"],
        evidence="学生不理解",  # 触发精确空洞词汇
        severity="P1",
        fix_scope="正文"
    )
    state_fail = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        diagnoses=[d_vague]
    )
    failures_vague = check_no_vague_reasons(state_fail)
    assert len(failures_vague) > 0

    # 场景 B: 诊断理由具体严谨
    d_concrete = DiagnosisRecord(
        record_id="d2",
        section_ref="1.1",
        checkpoint="goal",
        passed=False,
        labels=["jump"],
        evidence="自学者在此处困惑，因未交代判别式大于零的前提条件，推导链条断裂",
        severity="P1",
        fix_scope="正文"
    )
    state_pass = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        diagnoses=[d_concrete]
    )
    assert len(check_no_vague_reasons(state_pass)) == 0


def test_gate3_dependency_checks_cycle_and_closure():
    """测试 Gate 3: dependency_gate 拓扑无环与闭包"""
    c1 = ConceptNode(node_id="c1", name="概念1", kind="concept", statement="def1")
    c2 = ConceptNode(node_id="c2", name="概念2", kind="concept", statement="def2")
    
    # 场景 A: 存在环 (c1 -> c2 -> c1)
    e1 = DependencyEdge(from_id="c1", to_id="c2", relation="前置依赖")
    e2 = DependencyEdge(from_id="c2", to_id="c1", relation="前置依赖")
    state_cycle = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        nodes=[c1, c2], edges=[e1, e2]
    )
    failures_cycle = check_graph_acyclic(state_cycle)
    assert len(failures_cycle) > 0
    assert failures_cycle[0]["route_to"] == "cycle_detected"
    assert failures_cycle[0]["severity"] == "P0_stop"

    # 场景 B: 依赖悬空 (指向不存在的 c3)
    e3 = DependencyEdge(from_id="c1", to_id="c3", relation="前置依赖")
    state_dangling = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        nodes=[c1, c2], edges=[e3]
    )
    failures_closure = check_dependencies_closure(state_dangling)
    assert len(failures_closure) > 0


def test_gate4_pedagogy_checks_sections_and_obvious_skips():
    """测试 Gate 4: pedagogy_gate 单元小节完整度与跳步违禁词"""
    # 场景 A: 含有“显然”违禁词
    u_bad = LearningUnit(
        unit_id="u1",
        title="函数的单调性",
        objectives=["能证明函数的单调性"],
        node_refs=["c1"],
        completion_criteria="完成全部随堂测试",
        sections={"导言": "显然易见，当x增大时y也增大。"}
    )
    state_bad = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        units=[u_bad]
    )
    failures_skip = check_no_obvious_step_skips(state_bad)
    assert len(failures_skip) > 0
    assert failures_skip[0]["route_to"] == "obvious_jump"

    # 场景 B: 缺少必需小节 (未满 11 个核心要素)
    failures_sec = check_minimal_unit_sections(state_bad)
    assert len(failures_sec) > 0
    assert failures_sec[0]["route_to"] == "missing_sections"


def test_gate5_feedback_checks_hints_and_fields():
    """测试 Gate 5: feedback_gate 任务分层提示与字段完整性"""
    # 场景 A: 缺少第三层提示
    t_incomplete = Task(
        task_id="t1",
        unit_id="u1",
        source_refs=["s1"],
        objective="掌握定义",
        task_type="observe",
        prompt="求函数定义域",
        expected_evidence="正确列出不等式",
        answer="x > 0",
        analysis="分母不为零",
        hint_1="观察分母",
        hint_2="分母不能为零",
        hint_3="",  # 第三层提示为空！
        error_cause="忘记排除零",
        retry_task="求 1/(x-1) 定义域",
        boundary_note="注意开闭区间"
    )
    state_incomplete = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        tasks=[t_incomplete]
    )
    failures_hint = check_layered_hints(state_incomplete)
    assert len(failures_hint) > 0
    assert failures_hint[0]["route_to"] == "insufficient_hints"


def test_gate7_output_checks_formula_conservation():
    """测试 Gate 7: output_gate 公式括号与环境配平"""
    # 场景 A: 公式未闭合
    state_unpaired = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        good_md="这里有一个未闭合公式 $f(x) = x^2 之后的文字"
    )
    failures_formula = check_formula_conservation(state_unpaired)
    assert len(failures_formula) > 0
    assert failures_formula[0]["route_to"] == "formula_drift"

    # 场景 B: 公式成对闭合
    state_paired = GraphState(
        raw_files=["a.pdf"], discipline="math", good_md_path="out.md",
        good_md="这里是闭合公式 $f(x) = x^2$ 以及块级公式 $$\\int x dx$$ 结束。"
    )
    assert len(check_formula_conservation(state_paired)) == 0
