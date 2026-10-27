# -*- coding: utf-8 -*-
"""
lang.gates.checks_feedback
--------------------------
反馈门禁阶段 E 强化检查规则集。
包含再练答案检查、答案解答自洽性检查、提示递进性检查等。
"""

from __future__ import annotations
import difflib
import re
from typing import Any, Sequence


class CheckFailures(list):
    """
    门禁失败结果集合。
    兼容 list 接口，并提供 .passed 与 .failures 属性。
    """
    @property
    def passed(self) -> bool:
        return len(self) == 0

    @property
    def failures(self) -> list:
        return list(self)


def _get_tasks(state: Any) -> Sequence[Any]:
    tasks = getattr(state, "tasks", None)
    if tasks is None and isinstance(state, dict):
        tasks = state.get("tasks", [])
    return tasks or []


def _get_field(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        val = obj.get(name)
    else:
        val = getattr(obj, name, None)
    return val if val is not None else default


def check_retry_has_answer(state: Any) -> CheckFailures:
    """
    遍历 state.tasks，检查每个 task 若没有 retry_answer (not (t.retry_answer or "").strip())，则汇报错误。
    """
    failures = []
    tasks = _get_tasks(state)

    for t in tasks:
        task_id = str(_get_field(t, "task_id", "unknown"))
        retry_ans = str(_get_field(t, "retry_answer", ""))
        if not retry_ans.strip():
            failures.append({
                "check": "check_retry_has_answer",
                "target": task_id,
                "route_to": "default",
                "msg": f"任务 {task_id} 缺少再练答案 (retry_answer 为空)",
                "severity": "P1"
            })

    return CheckFailures(failures)


def _is_answer_in_solution(answer_str: str, solution_str: str) -> bool:
    """
    判断答案是否出现在规范解答中：
    1) 去除空格后，t.answer 是否出现在 t.worked_solution 中
    2) 若答案形如 {a, b, c} 集合字面量，检查所有元素是否都出现在解答中
    """
    ans = answer_str.strip()
    sol = solution_str.strip()
    if not ans or not sol:
        return False

    ans_clean = "".join(ans.split())
    sol_clean = "".join(sol.split())

    # 1) 整体去空格比对
    if ans_clean in sol_clean:
        return True

    # 2) 集合字面量比对（支持 {a, b, c}、\{a, b, c\} 及 \left\{...\right\} 等形式）
    stripped = ans.strip("$").strip()
    inner = None
    if stripped.startswith(r"\left\{") and stripped.endswith(r"\right\}"):
        inner = stripped[len(r"\left\{"):-len(r"\right\}")].strip()
    elif stripped.startswith(r"\{") and stripped.endswith(r"\}"):
        inner = stripped[2:-2].strip()
    elif stripped.startswith("{") and stripped.endswith("}"):
        inner = stripped[1:-1].strip()

    if inner is not None:
        # 按逗号（支持英文与中文逗号）切分元素
        raw_elements = [e.strip() for e in re.split(r"[,，]", inner) if e.strip()]
        if raw_elements:
            sol_no_dollar = sol_clean.replace("$", "")
            for elem in raw_elements:
                elem_clean = "".join(elem.split())
                elem_no_dollar = elem_clean.replace("$", "")
                found = (elem_clean in sol_clean) or (bool(elem_no_dollar) and elem_no_dollar in sol_no_dollar)
                if not found:
                    return False
            return True

    return False


def check_answer_in_solution(state: Any) -> CheckFailures:
    """
    检查 t.answer 与 t.worked_solution 的自洽性：
    1) 去除空格后，t.answer 是否出现在 t.worked_solution 中
    2) 若答案形如 {a, b, c} 集合字面量，检查所有元素是否都出现在解答中
    如果不匹配，记录错误。
    """
    failures = []
    tasks = _get_tasks(state)

    for t in tasks:
        task_id = str(_get_field(t, "task_id", "unknown"))
        ans = str(_get_field(t, "answer", ""))
        sol = str(_get_field(t, "worked_solution", ""))

        if not _is_answer_in_solution(ans, sol):
            failures.append({
                "check": "check_answer_in_solution",
                "target": task_id,
                "route_to": "default",
                "msg": f"任务 {task_id} 答案与规范解答不自洽: answer='{ans}' 未在 worked_solution 中出现",
                "severity": "P1"
            })

    return CheckFailures(failures)


def check_hints_progressive(state: Any) -> CheckFailures:
    """
    提示递进性检查：
    1) hint_1, hint_2, hint_3 两两之间 difflib 相似度不得 > 0.9
    2) 长度必须递增：len(h1) <= len(h2) <= len(h3)
    3) hint_1 不能直接包含 answer（泄底）
    """
    failures = []
    tasks = _get_tasks(state)

    for t in tasks:
        task_id = str(_get_field(t, "task_id", "unknown"))
        h1 = str(_get_field(t, "hint_1", ""))
        h2 = str(_get_field(t, "hint_2", ""))
        h3 = str(_get_field(t, "hint_3", ""))
        ans = str(_get_field(t, "answer", "")).strip()

        # 1) hint_1, hint_2, hint_3 两两之间 difflib 相似度不得 > 0.9
        pairs = [
            ("hint_1", "hint_2", h1, h2),
            ("hint_2", "hint_3", h2, h3),
            ("hint_1", "hint_3", h1, h3),
        ]
        for name_a, name_b, val_a, val_b in pairs:
            # 两者均非空时计算文本相似度
            if val_a and val_b:
                ratio = difflib.SequenceMatcher(None, val_a, val_b).ratio()
                if ratio > 0.9:
                    failures.append({
                        "check": "check_hints_progressive",
                        "target": task_id,
                        "route_to": "default",
                        "msg": f"任务 {task_id} 提示缺乏区分度: {name_a} 与 {name_b} 相似度过高 ({ratio:.2f} > 0.9)",
                        "severity": "P1"
                    })

        # 2) 长度必须递增：len(h1) <= len(h2) <= len(h3)
        if not (len(h1) <= len(h2) <= len(h3)):
            failures.append({
                "check": "check_hints_progressive",
                "target": task_id,
                "route_to": "default",
                "msg": f"任务 {task_id} 提示长度未递增: len(hint_1)={len(h1)}, len(hint_2)={len(h2)}, len(hint_3)={len(h3)}",
                "severity": "P1"
            })

        # 3) hint_1 不能直接包含 answer（泄底）
        if ans:
            ans_clean = "".join(ans.split())
            h1_clean = "".join(h1.split())
            ans_no_dollar = ans_clean.replace("$", "")
            h1_no_dollar = h1_clean.replace("$", "")

            is_leaked = (ans in h1)
            if not is_leaked and len(ans_clean) >= 2 and ans_clean in h1_clean:
                is_leaked = True
            elif not is_leaked and len(ans_no_dollar) >= 2 and ans_no_dollar in h1_no_dollar:
                is_leaked = True

            if is_leaked:
                failures.append({
                    "check": "check_hints_progressive",
                    "target": task_id,
                    "route_to": "default",
                    "msg": f"任务 {task_id} hint_1 直接包含答案 (answer='{ans}')，违反防泄底规则",
                    "severity": "P1"
                })

    return CheckFailures(failures)


# 检查函数注册字典
CHECKS = {
    "check_retry_has_answer": check_retry_has_answer,
    "check_answer_in_solution": check_answer_in_solution,
    "check_hints_progressive": check_hints_progressive,
}
