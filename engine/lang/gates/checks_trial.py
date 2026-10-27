# -*- coding: utf-8 -*-
"""
lang.gates.checks_trial
-----------------------
学生试读质量门禁检查函数集合（阶段 F 新增）。
严格防范模板化试读、空洞理由与虚假锚点。
"""

from __future__ import annotations
import re
import difflib
from itertools import combinations
from collections import defaultdict
from typing import Any


class CheckFailures(list):
    """
    检查失败列表包装类。
    继承自 list 以保持与 list[dict[str, Any]] 类型兼容，
    同时提供 .passed 与 .failures 属性以兼容自动化测试判定。
    """
    @property
    def passed(self) -> bool:
        return len(self) == 0

    @property
    def failures(self) -> list:
        return list(self)


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """辅助读取模型属性或字典键值"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _latest_reviews(state: Any) -> list[Any]:
    """
    过滤并获取最新试读记录。
    state.reviews 是通过 operator.add 累加的，重跑会追加。
    只过滤出 kind == "student_trial" 的记录，
    并以 (r.reviewer, r.target) 为键保留最新一条记录。返回 list(latest.values())。
    """
    latest: dict[tuple[Any, Any], Any] = {}
    reviews = _get_attr(state, "reviews", []) or []
    for r in reviews:
        kind = _get_attr(r, "kind")
        if kind == "student_trial":
            reviewer = _get_attr(r, "reviewer")
            target = _get_attr(r, "target")
            latest[(reviewer, target)] = r
    return list(latest.values())


def check_trial_attempts_structure(state: Any) -> CheckFailures:
    """
    基于 _latest_reviews(state)：
    1) 每条 review 必须有 attempts（not r.attempts 报错）
    2) a.task_id 必须属于该单元对应的 tasks（通过 unit_id 检查）
    3) not a.submitted_answer.strip() 报错
    4) len(a.decision_reason.strip()) < 10 报错
    """
    failures = CheckFailures()
    reviews = _latest_reviews(state)

    # 预先构建 unit_id -> 任务 ID 集合映射
    tasks_by_unit: dict[str, set[str]] = defaultdict(set)
    for t in (_get_attr(state, "tasks", []) or []):
        u_id = _get_attr(t, "unit_id")
        t_id = _get_attr(t, "task_id")
        if u_id and t_id:
            tasks_by_unit[str(u_id)].add(str(t_id))

    for r in reviews:
        target = str(_get_attr(r, "target", "") or "")
        attempts = _get_attr(r, "attempts", None)

        # 1) 每条 review 必须有 attempts（not r.attempts 报错）
        if not attempts:
            failures.append({
                "check": "check_trial_attempts_structure",
                "target": target,
                "route_to": "default",
                "msg": f"试读评审 [{target}] 缺少 attempts 作答记录",
                "severity": "P1",
            })
            continue

        valid_tasks = tasks_by_unit.get(target, set())

        for a in attempts:
            a_task_id = str(_get_attr(a, "task_id", "") or "")
            submitted_answer = str(_get_attr(a, "submitted_answer", "") or "")
            decision_reason = str(_get_attr(a, "decision_reason", "") or "")

            # 2) a.task_id 必须属于该单元对应的 tasks（通过 unit_id 检查）
            if not a_task_id or a_task_id not in valid_tasks:
                failures.append({
                    "check": "check_trial_attempts_structure",
                    "target": target,
                    "route_to": "default",
                    "msg": f"作答记录 task_id '{a_task_id}' 不属于单元 [{target}] 对应的任务列表",
                    "severity": "P1",
                })

            # 3) not a.submitted_answer.strip() 报错
            if not submitted_answer.strip():
                failures.append({
                    "check": "check_trial_attempts_structure",
                    "target": target,
                    "route_to": "default",
                    "msg": f"单元 [{target}] 任务 [{a_task_id}] 的作答答案 submitted_answer 为空",
                    "severity": "P1",
                })

            # 4) len(a.decision_reason.strip()) < 10 报错
            if len(decision_reason.strip()) < 10:
                failures.append({
                    "check": "check_trial_attempts_structure",
                    "target": target,
                    "route_to": "default",
                    "msg": f"单元 [{target}] 任务 [{a_task_id}] 的判定理由 decision_reason 长度不足 10 字符: '{decision_reason.strip()}'",
                    "severity": "P1",
                })

    return failures


def check_trial_anchor_in_text(state: Any) -> CheckFailures:
    """
    基于 _latest_reviews(state)：
    检查每个 attempt 的 evidence_anchor：
    1) len(anchor) < 10 报错
    2) anchor not in state.good_md 报错（必须在正文中出现）
    """
    failures = CheckFailures()
    reviews = _latest_reviews(state)
    good_md = str(_get_attr(state, "good_md", "") or "")

    for r in reviews:
        target = str(_get_attr(r, "target", "") or "")
        attempts = _get_attr(r, "attempts", []) or []

        for a in attempts:
            a_task_id = str(_get_attr(a, "task_id", "") or "")
            anchor = _get_attr(a, "evidence_anchor", "")
            anchor_str = str(anchor or "").strip()

            # 1) len(anchor) < 10 报错
            if len(anchor_str) < 10:
                failures.append({
                    "check": "check_trial_anchor_in_text",
                    "target": target,
                    "route_to": "default",
                    "msg": f"单元 [{target}] 任务 [{a_task_id}] 的 evidence_anchor 长度不足 10 字符: '{anchor_str}'",
                    "severity": "P1",
                })
            # 2) anchor not in state.good_md 报错（必须在正文中出现）
            elif anchor_str not in good_md:
                failures.append({
                    "check": "check_trial_anchor_in_text",
                    "target": target,
                    "route_to": "default",
                    "msg": f"单元 [{target}] 任务 [{a_task_id}] 的 evidence_anchor 未在正文 good_md 中出现: '{anchor_str}'",
                    "severity": "P1",
                })

    return failures


def check_no_template_reviews(state: Any) -> CheckFailures:
    """
    基于 _latest_reviews(state)：
    反模板化检查：
    同一 reviewer 跨单元的文本不得雷同：
    按 reviewer 分组收集 text = re.sub(r"\\s+", "", " ".join(r.findings))
    对该 reviewer 的不同 target 两两比对 difflib.SequenceMatcher(None, x, y).ratio()
    若 ratio > 0.9，报错疑似模板复制。
    """
    failures = CheckFailures()
    reviews = _latest_reviews(state)

    reviewer_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in reviews:
        reviewer = str(_get_attr(r, "reviewer", "") or "")
        target = str(_get_attr(r, "target", "") or "")
        findings = _get_attr(r, "findings", []) or []
        text = re.sub(r"\s+", "", " ".join(str(f) for f in findings))
        reviewer_groups[reviewer].append((target, text))

    for reviewer, items in reviewer_groups.items():
        if len(items) < 2:
            continue
        for (t1, x), (t2, y) in combinations(items, 2):
            ratio = difflib.SequenceMatcher(None, x, y).ratio()
            if ratio > 0.9:
                failures.append({
                    "check": "check_no_template_reviews",
                    "target": f"{t1},{t2}",
                    "route_to": "default",
                    "msg": f"评审人 [{reviewer}] 跨单元 ({t1} 与 {t2}) 评审文本相似度为 {ratio:.2f} > 0.9，疑似模板复制",
                    "severity": "P1",
                })

    return failures


# 顶部导出规范
CHECKS = {
    "check_trial_attempts_structure": check_trial_attempts_structure,
    "check_trial_anchor_in_text": check_trial_anchor_in_text,
    "check_no_template_reviews": check_no_template_reviews,
}

__all__ = [
    "CheckFailures",
    "CHECKS",
    "check_trial_attempts_structure",
    "check_trial_anchor_in_text",
    "check_no_template_reviews",
]
