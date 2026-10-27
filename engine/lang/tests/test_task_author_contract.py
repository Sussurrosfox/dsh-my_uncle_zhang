# -*- coding: utf-8 -*-
"""
test_task_author_contract.py
----------------------------
阶段 E.1 & E.2 任务卡片与 task_author 契约测试。
验证 Task 模型、反馈门禁规则与渲染器的一致性。
"""

import pytest
from lang.state import Task, GraphState
from lang.mock_content import MOCK_TASKS, get_mock_state_kwargs
from lang.gates.checks_feedback import (
    check_retry_has_answer,
    check_answer_in_solution,
    check_hints_progressive,
    CHECKS as FEEDBACK_CHECKS,
)
from lang.task_renderer import render_task_block, render_tasks_into_good_md


def test_task_model_fields_and_defaults():
    """验证 Task 模型字段包含全部新需求字段"""
    t = Task(
        task_id="t_001",
        unit_id="u_001",
        prompt="测试题目",
        hint_1="提示1",
        hint_2="提示2更长一些",
        hint_3="提示3更加详细完整",
        answer="A",
        worked_solution="解析：因为...所以选A",
        common_errors=["选B"],
        error_reasons=["概念不清"],
        retry_prompt="再练一道题",
        retry_answer="B",
        boundary_note="边界注意",
    )
    assert t.task_id == "t_001"
    assert t.retry_answer == "B"
    assert t.boundary_note == "边界注意"
    assert len(t.common_errors) == 1
    assert len(t.error_reasons) == 1


def test_feedback_checks_on_mock_content():
    """验证标准 mock 数据能完全通过反馈检查"""
    state_kwargs = get_mock_state_kwargs()
    # 为 mock 任务补充 worked_solution 保证 check_answer_in_solution 匹配
    for t in state_kwargs["tasks"]:
        if not t.worked_solution:
            t.worked_solution = f"详细解析：根据性质推导可知，答案为：{t.answer}"

    state = GraphState(**state_kwargs)

    res_retry = check_retry_has_answer(state)
    assert res_retry.passed, f"check_retry_has_answer 失败: {res_retry.failures}"

    res_sol = check_answer_in_solution(state)
    assert res_sol.passed, f"check_answer_in_solution 失败: {res_sol.failures}"

    res_hints = check_hints_progressive(state)
    assert res_hints.passed, f"check_hints_progressive 失败: {res_hints.failures}"


def test_check_retry_has_answer_catches_empty():
    """测试再练答案缺失被精准拦截"""
    bad_task = Task(
        task_id="bad_t1",
        unit_id="u1",
        prompt="测试",
        hint_1="方向",
        hint_2="结构长一些",
        hint_3="推导细节更长一些",
        answer="42",
        worked_solution="结果是42",
        retry_prompt="再练",
        retry_answer="",  # 缺失
    )
    state = GraphState(raw_files=["a.md"], tasks=[bad_task])
    res = check_retry_has_answer(state)
    assert not res.passed
    assert any("retry_answer" in f["msg"] or "未配置" in f["msg"] for f in res.failures)


def test_check_answer_in_solution_catches_mismatch():
    """测试答案未在解析中出现被拦截"""
    bad_task = Task(
        task_id="bad_t2",
        unit_id="u1",
        prompt="测试",
        hint_1="方向",
        hint_2="结构长一些",
        hint_3="推导细节更长一些",
        answer="999",
        worked_solution="完全没有提及正确数字",
        retry_prompt="再练",
        retry_answer="1",
    )
    state = GraphState(raw_files=["a.md"], tasks=[bad_task])
    res = check_answer_in_solution(state)
    assert not res.passed


def test_check_hints_progressive_catches_leak_and_inversion():
    """测试 hint_1 泄底与长度倒挂"""
    # 1. 泄底
    leak_task = Task(
        task_id="leak_t",
        unit_id="u1",
        prompt="测试",
        hint_1="答案就是100很显然",
        hint_2="结构提示更长一点点",
        hint_3="推导细节更加长一些呢",
        answer="100",
        worked_solution="解析：100",
        retry_prompt="再练",
        retry_answer="100",
    )
    state_leak = GraphState(raw_files=["a.md"], tasks=[leak_task])
    res_leak = check_hints_progressive(state_leak)
    assert not res_leak.passed
    assert any("泄底" in f["msg"] or "包含" in f["msg"] for f in res_leak.failures)

    # 2. 长度倒挂 (h1 比 h2 长)
    invert_task = Task(
        task_id="invert_t",
        unit_id="u1",
        prompt="测试",
        hint_1="这是一个非常非常非常非常非常长的第一层提示",
        hint_2="短提示2",
        hint_3="短提示3",
        answer="5",
        worked_solution="解析：5",
        retry_prompt="再练",
        retry_answer="5",
    )
    state_invert = GraphState(raw_files=["a.md"], tasks=[invert_task])
    res_invert = check_hints_progressive(state_invert)
    assert not res_invert.passed
    assert any("递增" in f["msg"] or "倒挂" in f["msg"] for f in res_invert.failures)


def test_task_renderer_render_and_markdown_embed():
    """测试任务渲染器输出结构以及 Markdown 占位符替换"""
    t = Task(
        task_id="t_render_1",
        unit_id="u1",
        task_type="即时核验",
        prompt="计算 1 + 1",
        hint_1="回忆加法",
        hint_2="1 加 1 的定义",
        hint_3="把 1 累加 1 次",
        answer="2",
        worked_solution="1 + 1 = 2",
        common_errors=["算成3"],
        error_reasons=["粗心"],
        retry_prompt="计算 2 + 2",
        retry_answer="4",
        boundary_note="皮亚诺公理",
    )
    card_html = render_task_block(t)
    assert "#### 练习（即时核验）" in card_html
    assert "<details><summary>提示 1（方向性）</summary>" in card_html
    assert "<details><summary>提示 2（结构性）</summary>" in card_html
    assert "<details><summary>提示 3（局部操作）</summary>" in card_html
    assert "<details><summary>答案与解析</summary>" in card_html
    assert "<details><summary>再练一题</summary>" in card_html
    assert "**再练答案**：4" in card_html
    assert "> 边界提示：皮亚诺公理" in card_html

    # 测试 Markdown 嵌入
    md_content = "# 测试章节\n\n{{task:t_render_1}}\n\n{{task:not_exist}}\n"
    rendered_md = render_tasks_into_good_md(md_content, [t])
    assert "{{task:t_render_1}}" not in rendered_md
    assert "#### 练习（即时核验）" in rendered_md
    # 未匹配到的占位符应原样保留供 output_gate 拦截
    assert "{{task:not_exist}}" in rendered_md
