# -*- coding: utf-8 -*-
"""
攻击性回归测试套件 (audit_it.md §6 与 audit_it_update.md 阶段 J)
-----------------------------------------------------------
十条确定性门禁攻击测试，验证系统在各类篡改、失效与污染下均实现 fail closed，
并在修复后规范通过。
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
import pytest

from lang.state import (
    GraphState,
    GateResult,
    ReviewRecord,
    TaskAttempt,
    Task,
    ConceptNode,
    ReleaseManifest,
)
from lang.snapshot import compute_state_hash, new_build_id
from lang.gates.deterministic import (
    REQUIRED_GATES,
    validate_gates_current,
)

# 阶段 E/F/G/H 检查模块导入（带 deterministic 回退容错）
try:
    from lang.gates.checks_output import (
        check_no_unresolved_placeholders,
        check_formula_structure,
        check_no_internal_leaks,
    )
except ImportError:
    from lang.gates.deterministic import (  # type: ignore
        check_no_unresolved_placeholders,
        check_formula_structure,
        check_no_internal_leaks,
    )

try:
    from lang.gates.checks_feedback import (
        check_retry_has_answer,
        check_answer_in_solution,
    )
except ImportError:
    from lang.gates.deterministic import (  # type: ignore
        check_retry_has_answer,
        check_answer_in_solution,
    )

try:
    from lang.gates.checks_trial import (
        check_no_template_reviews,
        check_trial_attempts_structure,
    )
except ImportError:
    from lang.gates.deterministic import (  # type: ignore
        check_no_template_reviews,
        check_trial_attempts_structure,
    )


def _bound_result(gate: str, state: GraphState, passed: bool = True) -> GateResult:
    """构造与当前 state 的 build_id 和 state_hash 精确绑定的 GateResult"""
    return GateResult(
        gate=gate,
        passed=passed,
        failures=[] if passed else [{"check": f"check_{gate}", "msg": "failed"}],
        decided_by="auto",
        decided_at="2026-01-01T00:00:00+00:00",
        build_id=state.build_id,
        state_hash=compute_state_hash(state),
    )


def _state_with_all_pass() -> GraphState:
    """构造全 gate 均通过且绑定的基准图状态"""
    s = GraphState(build_id=new_build_id(), good_md="正文" * 60)
    s.gate_results = [
        _bound_result(g, s) for g in REQUIRED_GATES + ["version_gate"]
    ]
    return s


# =========================================================================
# 1. 历史绿灯失效攻击 (stale_invalidates_all)
# =========================================================================
def test_stale_invalidates_all():
    """
    1. 全 pass 状态，篡改 good_md 一个字，旧绿灯全部失效作废；
       断言 validate_gates_current(s) != [] 且重新绑定后通过。
    """
    s = _state_with_all_pass()
    assert validate_gates_current(s) == []

    # 破坏动作：篡改 good_md 一个字
    s.good_md += "篡改"

    errs = validate_gates_current(s)
    # 所有旧门禁由于 state_hash 不一致必须全部失效，拒绝沿用旧绿灯
    assert len(errs) > 0
    for gate_name in REQUIRED_GATES + ["version_gate"]:
        assert any(gate_name in e for e in errs)

    # 修复动作：重新跑门禁并绑定当前篡改后的快照指纹
    s.gate_results = [
        _bound_result(g, s) for g in REQUIRED_GATES + ["version_gate"]
    ]
    assert validate_gates_current(s) == []


# =========================================================================
# 2. 跨构建混合记录攻击 (mixed_history_rejected)
# =========================================================================
def test_mixed_history_rejected():
    """
    2. 混入旧 build_id 的 gate_result，断言 validate_gates_current 报错包含对应 gate；
       恢复为当前 build_id 后通过。
    """
    s = _state_with_all_pass()
    assert validate_gates_current(s) == []

    # 破坏动作：将第一个门禁 (source_gate) 替换为来自旧构建的记录
    target_gate = s.gate_results[0].gate
    old_record = s.gate_results[0].model_copy(update={"build_id": "build-legacy-999"})
    s.gate_results = [old_record] + s.gate_results[1:]

    # 旧 build_id 不构成当前构建的有效证明 → 必须报错拒绝
    errs = validate_gates_current(s)
    assert any(target_gate in e for e in errs)

    # 修复动作：纠正 build_id 为当前构建
    s.gate_results[0] = s.gate_results[0].model_copy(update={"build_id": s.build_id})
    assert validate_gates_current(s) == []


# =========================================================================
# 3. 路径绑定与静默回退防御 (path_binding)
# =========================================================================
def test_path_binding(tmp_path):
    """
    3. runner 对不存在的 state_file 必须报错退出 (returncode != 0) 且输出包含'不存在'；
       cwd 指向插件根目录。
    """
    plugin_root = Path(__file__).resolve().parents[2]
    for p in Path(__file__).resolve().parents:
        if (p / "scripts" / "runner.py").is_file():
            plugin_root = p
            break

    nope_file = str(tmp_path / "nonexistent_state.json")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [
            sys.executable,
            "scripts/runner.py",
            "gate",
            "--gate",
            "all",
            "--state-file",
            nope_file,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(plugin_root),
        env=env,
    )
    assert r.returncode != 0
    combined_output = r.stdout + r.stderr
    assert "不存在" in combined_output


# =========================================================================
# 4. 试读报告虚构防御 (trial_fabrication)
# =========================================================================
def test_trial_fabrication():
    """
    4. 模板化 reviews 且无 attempts，断言 check_no_template_reviews 与
       check_trial_attempts_structure 拒绝；异构评语带合法 attempts 通过。
    """
    # 破坏动作：三个单元复用同一段评审评语，且无任何 attempts
    rs = [
        ReviewRecord(
            reviewer="strong",
            kind="student_trial",
            target=f"u{i}",
            findings=["整体写得很好，例题清晰，逻辑严密，可以顺利自学。"],
            stuck_points=[],
            decision="pass",
        )
        for i in (1, 2, 3)
    ]
    s_bad = GraphState(reviews=rs, good_md="正文内容" * 50)
    assert not check_no_template_reviews(s_bad).passed
    assert not check_trial_attempts_structure(s_bad).passed

    # 修复动作：各单元提供不同维度的差异化反馈，并具备真实任务作答及正文锚点
    t1 = Task(task_id="task_u1_01", unit_id="u1", objective="o", task_type="observe",
              prompt="p", expected_evidence="e", answer="a", worked_solution="推导得出 a",
              hint_1="h1", hint_2="h2", hint_3="h3", retry_task="rt", retry_answer="ra")
    t2 = Task(task_id="task_u2_01", unit_id="u2", objective="o", task_type="observe",
              prompt="p", expected_evidence="e", answer="b", worked_solution="推导得出 b",
              hint_1="h1", hint_2="h2", hint_3="h3", retry_task="rt", retry_answer="ra")
    t3 = Task(task_id="task_u3_01", unit_id="u3", objective="o", task_type="observe",
              prompt="p", expected_evidence="e", answer="c", worked_solution="推导得出 c",
              hint_1="h1", hint_2="h2", hint_3="h3", retry_task="rt", retry_answer="ra")

    good_text = (
        "这是集合概念引入的单元一核心描述文字。" * 10
        + "这是元素互异性规则展开的单元二说明文字。" * 10
        + "这是子集与真子集包含关系的单元三深入分析。" * 10
    )
    rs_fixed = [
        ReviewRecord(
            reviewer="strong",
            kind="student_trial",
            target="u1",
            findings=["集合的概念阐明得非常清楚，维恩图帮助理解。"],
            stuck_points=[],
            decision="pass",
            attempts=[
                TaskAttempt(
                    task_id="task_u1_01",
                    submitted_answer="a",
                    evidence_anchor=good_text[0:20],
                    first_attempt_correct=True,
                    decision_reason="作答完全符合预期标准要求并给出详细推理过程",
                )
            ],
        ),
        ReviewRecord(
            reviewer="strong",
            kind="student_trial",
            target="u2",
            findings=["元素互异性这一卡点分析透彻，例题针对性强。"],
            stuck_points=[],
            decision="pass",
            attempts=[
                TaskAttempt(
                    task_id="task_u2_01",
                    submitted_answer="b",
                    evidence_anchor=good_text[100:120],
                    first_attempt_correct=True,
                    decision_reason="作答完全符合预期标准要求并给出详细推理过程",
                )
            ],
        ),
        ReviewRecord(
            reviewer="strong",
            kind="student_trial",
            target="u3",
            findings=["子集与真子集的包含关系对比鲜明，易错点提示很到位。"],
            stuck_points=[],
            decision="pass",
            attempts=[
                TaskAttempt(
                    task_id="task_u3_01",
                    submitted_answer="c",
                    evidence_anchor=good_text[200:220],
                    first_attempt_correct=True,
                    decision_reason="作答完全符合预期标准要求并给出详细推理过程",
                )
            ],
        ),
    ]
    s_fixed = GraphState(tasks=[t1, t2, t3], reviews=rs_fixed, good_md=good_text)
    assert check_no_template_reviews(s_fixed).passed
    assert check_trial_attempts_structure(s_fixed).passed


# =========================================================================
# 5. 任务交付契约防御 (task_contract)
# =========================================================================
def test_task_contract():
    """
    5. task 没有 retry_answer，或正文残留未解析占位符，
       断言 check_retry_has_answer 与 check_no_unresolved_placeholders 拒绝；
       补齐答案且正文正常渲染后通过。
    """
    # 破坏动作：Task 缺少 retry_answer，正文残留 {{task:...}}
    t_bad = Task(
        task_id="task_u1_01",
        unit_id="u1",
        source_refs=["s1"],
        objective="o",
        task_type="observe",
        prompt="p",
        prerequisite_refs=[],
        expected_evidence="e",
        answer="a",
        worked_solution="含答案 a 的详尽过程",
        common_errors=["c"],
        error_reasons=["r"],
        hint_1="h1",
        hint_2="h2 更长一些的结构性提示",
        hint_3="h3 最具体最长步骤的局部操作提示",
        retry_task="rt",
        retry_answer="",  # 破坏：再练无答案
    )
    assert not check_retry_has_answer(GraphState(tasks=[t_bad])).passed
    s_placeholder = GraphState(good_md="{{task:task_u1_01}}", tasks=[t_bad])
    assert not check_no_unresolved_placeholders(s_placeholder).passed

    # 修复动作：补齐 retry_answer 且正文无残留占位符
    t_fixed = t_bad.model_copy(update={"retry_answer": "ra"})
    assert check_retry_has_answer(GraphState(tasks=[t_fixed])).passed
    s_fixed = GraphState(good_md="正文内容已完整渲染完毕，无占位符。", tasks=[t_fixed])
    assert check_no_unresolved_placeholders(s_fixed).passed


# =========================================================================
# 6. 答案与解答不匹配防御 (answer_mismatch)
# =========================================================================
def test_answer_mismatch():
    """
    6. 答案为 {1, 2, 3} 但解答中只有 {4, 5}，断言 check_answer_in_solution 拒绝；
       解答包含标准答案时通过。
    """
    # 破坏动作：标准答案不在解析文本中出现
    t_bad = Task(
        task_id="t1",
        unit_id="u1",
        source_refs=["s1"],
        objective="o",
        task_type="observe",
        prompt="p",
        prerequisite_refs=[],
        expected_evidence="e",
        answer="{1, 2, 3}",
        worked_solution="……所以最终集合为 {4, 5}",  # 破坏：答非所解
        common_errors=["c"],
        error_reasons=["r"],
        hint_1="h1",
        hint_2="h2",
        hint_3="h3",
        retry_task="rt",
        retry_answer="ra",
    )
    assert not check_answer_in_solution(GraphState(tasks=[t_bad])).passed

    # 修复动作：解答中清晰包含标准答案
    t_fixed = t_bad.model_copy(update={"worked_solution": "经步骤化推导，最终求解所得集合为 {1, 2, 3}"})
    assert check_answer_in_solution(GraphState(tasks=[t_fixed])).passed


# =========================================================================
# 7. 公式渲染与结构合规 (formula_render)
# =========================================================================
def test_formula_render():
    """
    7. 公式含全角标点被拒，规范公式通过（check_formula_structure）。
    """
    # 破坏动作 1：全角括号错位进入数学段
    bad_bracket = "符号集 $\\mathbf{N}^*$（或 $\\mathbf{N}_+）$, \\mathbf{Z}$ 的写法" + "字" * 100
    assert not check_formula_structure(GraphState(good_md=bad_bracket)).passed

    # 破坏动作 2：公式内含全角逗号标点
    bad_comma = "满足方程式 $x + y = 1，z = 2$ 的解" + "字" * 100
    assert not check_formula_structure(GraphState(good_md=bad_comma)).passed

    # 破坏动作 3：花括号不平衡
    bad_brace = "计算集合 $A = \\{x | x > 0$ 的取值" + "字" * 100
    assert not check_formula_structure(GraphState(good_md=bad_brace)).passed

    # 修复版：标点符号与定界符规范
    good = "符号集 $\\mathbf{N}^*$（或 $\\mathbf{N}_+$），$\\mathbf{Z}$ 的写法" + "字" * 100
    assert check_formula_structure(GraphState(good_md=good)).passed


# =========================================================================
# 8. 内部泄露与敏感串防御 (source_leak)
# =========================================================================
@pytest.mark.parametrize(
    "poison",
    [
        "课本第 93-105 行",
        "详见 tasks.json",
        "见 task_u1_01",
        r"C:\Users\x\state.json",
        "待补充",
    ],
)
def test_source_leak(poison):
    """
    8. 注入各类敏感串（行号、内部文件名、裸任务ID、绝对路径、占位待补充），
       断言 check_no_internal_leaks 拒绝；纯净正文通过。
    """
    # 破坏版：正文夹带敏感内部泄露串
    s_poison = GraphState(good_md="正文内容展示" * 40 + poison + "正文后续" * 10)
    assert not check_no_internal_leaks(s_poison).passed

    # 修复版：纯净自学正文通过
    s_clean = GraphState(good_md="这是一篇没有任何内部泄露标记与源文件痕迹的规范自学教材正文。" * 20)
    assert check_no_internal_leaks(s_clean).passed


# =========================================================================
# 9. 伪差异可复现试读防御 (reproducible_trial)
# =========================================================================
def test_reproducible_trial():
    """
    9. 仅尾注不同的模板评审，断言 check_no_template_reviews 拒绝；
       真正异构评审通过。
    """
    # 破坏版：仅在末尾加上标号（1）、（2）、（3），相似度 > 0.9 的伪差异
    base = "本单元讲解清晰，例题合适，能够顺利自学完成全部练习"
    rs_pseudo = [
        ReviewRecord(
            reviewer="median",
            kind="student_trial",
            target=f"u{i}",
            findings=[base + f"（{i}）"],
            stuck_points=[],
            decision="pass",
            attempts=[
                TaskAttempt(
                    task_id=f"task_u{i}_01",
                    submitted_answer="a",
                    evidence_anchor="正文正文正文正文正文",
                    first_attempt_correct=True,
                    decision_reason="因为作答正确且过程完整",
                )
            ],
        )
        for i in (1, 2, 3)
    ]
    s_bad = GraphState(reviews=rs_pseudo, good_md="正文" * 50)
    assert not check_no_template_reviews(s_bad).passed

    # 修复版：针对各单元具体知识点的实质差异化评语
    rs_distinct = [
        ReviewRecord(
            reviewer="median",
            kind="student_trial",
            target="u1",
            findings=["集合元素的无序性很容易理解，但空集是任何集合的子集需要多思考。"],
            stuck_points=[],
            decision="pass",
        ),
        ReviewRecord(
            reviewer="median",
            kind="student_trial",
            target="u2",
            findings=["并集和交集的运算符号在初学时容易混淆，例题对比给得很直观。"],
            stuck_points=[],
            decision="pass",
        ),
        ReviewRecord(
            reviewer="median",
            kind="student_trial",
            target="u3",
            findings=["补集的全集范围必须提前明确，练习第3题很好地提醒了这一点。"],
            stuck_points=[],
            decision="pass",
        ),
    ]
    s_good = GraphState(reviews=rs_distinct, good_md="正文" * 50)
    assert check_no_template_reviews(s_good).passed


# =========================================================================
# 10. 审计一致性防御 (audit_consistency)
# =========================================================================
def test_audit_consistency():
    """
    10. manifest.state_hash 与当前 state 不一致，断言 export_check
        抛出 ExportVerificationError；指纹严格一致且结构自洽时通过。
    """
    from lang.exporters import export_check, ExportVerificationError

    s = _state_with_all_pass()
    s.nodes = [ConceptNode(node_id="c1", name="集合", kind="concept", statement="定义")]
    s.tasks = [
        Task(
            task_id="task_u1_01",
            unit_id="u1",
            objective="o",
            task_type="observe",
            prompt="p",
            expected_evidence="e",
            answer="a",
            worked_solution="由推导可知答案为 a",
            hint_1="h1",
            hint_2="h2",
            hint_3="h3",
            retry_task="rt",
            retry_answer="ra",
        )
    ]

    # 破坏动作：manifest.state_hash 指向伪造哈希
    s.manifest = ReleaseManifest(
        version="v2.0.0-deadbeef",
        build_id=s.build_id,
        state_hash="0" * 64,  # 破坏：与真实内容快照不一致
        input_hashes={},
        output_hashes={},
        tool_versions={},
        gate_results=s.gate_results,
        approver="release_manager:auto",
    )
    with pytest.raises(ExportVerificationError):
        export_check(s)

    # 修复动作：manifest.state_hash 严格复算对齐，且各 gate_results 均有效
    s.gate_results = [
        _bound_result(g, s) for g in REQUIRED_GATES + ["version_gate"]
    ]
    s.manifest = ReleaseManifest(
        version="v2.0.0-certified",
        build_id=s.build_id,
        state_hash=compute_state_hash(s),
        input_hashes={},
        output_hashes={},
        tool_versions={},
        gate_results=s.gate_results,
        approver="release_manager:auto",
    )
    # 校验通过，无异常抛出
    export_check(s)
