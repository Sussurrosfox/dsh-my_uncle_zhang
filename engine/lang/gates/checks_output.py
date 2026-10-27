# -*- coding: utf-8 -*-
"""
lang.gates.checks_output
------------------------
阶段 E.4 / G.1 / H.1 / H.2 新增的 output_gate 确定性检查函数集合。
"""

from __future__ import annotations
import re
from typing import Any
from lang.state import GraphState
from lang.gates.deterministic import CheckFailures

INTERNAL_LEAK_PATTERNS = [
    (r"第\s*\d+\s*[-–—~]\s*\d+\s*行", "源文件行号区间"),
    (r"课本第\s*\d+\s*行", "源文件行号"),
    (r"[A-Za-z]:\\\\", "绝对路径"),
    (r"tasks\.json", "工程文件名 tasks.json"),
    (r"state\.json", "工程文件名 state.json"),
    (r"task_[a-z0-9_]+", "裸任务 ID"),
    (r"\{\{|\}\}", "未解析模板占位符"),
    (r"TODO|TBD|FIXME|待补充|待完善", "占位文本"),
]


def check_no_unresolved_placeholders(state: GraphState) -> CheckFailures:
    """正文不得存在未解析的任务占位符 {{task:...}}"""
    failures = []
    leftover = re.findall(r"\{\{task:[A-Za-z0-9_\-]+\}\}", state.good_md or "")
    for x in leftover:
        failures.append({
            "check": "check_no_unresolved_placeholders",
            "target": "good_md",
            "route_to": "default",
            "msg": f"正文存在未解析任务占位符: {x}",
            "severity": "P1"
        })
    return CheckFailures(failures)


def check_no_raw_task_refs(state: GraphState) -> CheckFailures:
    """正文不得出现裸工程内部任务 ID task_*（应已被渲染为练习区块）"""
    failures = []
    refs = sorted(set(re.findall(r"task_[a-z0-9_]+", state.good_md or "")))
    for r in refs:
        failures.append({
            "check": "check_no_raw_task_refs",
            "target": "good_md",
            "route_to": "default",
            "msg": f"正文出现工程内部任务 ID: {r}（应已被渲染为练习区块）",
            "severity": "P1"
        })
    return CheckFailures(failures)


def check_formula_structure(state: GraphState) -> CheckFailures:
    """比 $ 配平更强的结构检查：
    1. 数学段内不得出现全角标点（精准命中 F-08 的 $\\mathbf{N}^*$）$, \\mathbf{Z}$ 错位）
    2. 每个数学段内花括号配平
    3. 数学段非空
    """
    failures = []
    text = state.good_md or ""
    for i, seg in enumerate(re.findall(r"\$([^$]+)\$", text)):
        if re.search(r"[，。；：（）、？！]", seg):
            failures.append({
                "check": "check_formula_structure",
                "target": "good_md",
                "route_to": "formula_drift",
                "msg": f"第 {i+1} 个数学段含全角标点: {seg[:40]}…",
                "severity": "P1"
            })
        if seg.count("{") != seg.count("}"):
            failures.append({
                "check": "check_formula_structure",
                "target": "good_md",
                "route_to": "formula_drift",
                "msg": f"第 {i+1} 个数学段花括号不配平: {seg[:40]}…",
                "severity": "P1"
            })
        if not seg.strip():
            failures.append({
                "check": "check_formula_structure",
                "target": "good_md",
                "route_to": "formula_drift",
                "msg": f"第 {i+1} 个数学段为空",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_no_internal_leaks(state: GraphState) -> CheckFailures:
    """检查正文是否命中内部泄露 denylist（行号、绝对路径、内部文件名、TODO标记等）"""
    failures = []
    text = state.good_md or ""
    for pattern, desc in INTERNAL_LEAK_PATTERNS:
        for m in re.finditer(pattern, text):
            line_no = text[: m.start()].count("\n") + 1
            failures.append({
                "check": "check_no_internal_leaks",
                "target": "good_md",
                "route_to": "default",
                "msg": f"正文第 {line_no} 行命中 denylist[{desc}]: {m.group(0)!r}",
                "severity": "P1"
            })
    return CheckFailures(failures)


def check_transfer_tasks_answered(state: GraphState) -> CheckFailures:
    """迁移题闭环检查：正文中每个迁移小节后 800 字符内必须有答案/折叠块，且 Task 模型中迁移任务必有 answer"""
    failures = []
    text = state.good_md or ""
    for m in re.finditer(r"迁移", text):
        window = text[m.start(): m.start() + 800]
        if "<details>" not in window and "答案" not in window:
            line_no = text[: m.start()].count("\n") + 1
            failures.append({
                "check": "check_transfer_tasks_answered",
                "target": "good_md",
                "route_to": "default",
                "msg": f"第 {line_no} 行附近的迁移题缺少答案区块",
                "severity": "P1"
            })
    for t in getattr(state, "tasks", []):
        if getattr(t, "task_type", "") == "迁移" and not (getattr(t, "answer", "") or "").strip():
            failures.append({
                "check": "check_transfer_tasks_answered",
                "target": t.task_id,
                "route_to": "default",
                "msg": f"迁移任务 {t.task_id} 无答案",
                "severity": "P1"
            })
    return CheckFailures(failures)


CHECKS = {
    "check_no_unresolved_placeholders": check_no_unresolved_placeholders,
    "check_no_raw_task_refs": check_no_raw_task_refs,
    "check_formula_structure": check_formula_structure,
    "check_no_internal_leaks": check_no_internal_leaks,
    "check_transfer_tasks_answered": check_transfer_tasks_answered,
}
