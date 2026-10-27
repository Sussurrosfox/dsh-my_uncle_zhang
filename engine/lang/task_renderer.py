# -*- coding: utf-8 -*-
"""
lang.task_renderer
------------------
阶段 E.2 任务卡片渲染与 Markdown 嵌入模块。
支持将 Task 对象转换为带分层折叠（题面 -> 提示1/2/3 -> 作答区 -> 答案解析 -> 再练）的交互式卡片，
并将占位符 {{task:<id>}} 替换入 good.md。
"""

from __future__ import annotations
import re
from typing import Any, Sequence

PLACEHOLDER_RE = re.compile(r"\{\{task:([A-Za-z0-9_\-]+)\}\}")


class _TaskProxy:
    """包装 Task 对象或字典，确保安全访问属性"""

    def __init__(self, task: Any):
        self._task = task

    def __getattr__(self, name: str) -> Any:
        if isinstance(self._task, dict):
            val = self._task.get(name)
        else:
            val = getattr(self._task, name, None)

        if val is None:
            if name in ("common_errors", "error_reasons"):
                return []
            return ""
        return val


def render_task_block(task: Any) -> str:
    """
    按照题面 → 分层提示（折叠）→ 作答区 → 答案解析（折叠）→ 再练（折叠）渲染。
    """
    t = _TaskProxy(task)

    errors = "\n".join(f"- {e}" for e in t.common_errors)
    reasons = "\n".join(f"- {r}" for r in t.error_reasons)
    retry_answer_line = (
        f"\n**再练答案**：{t.retry_answer}" if t.retry_answer else ""
    )
    boundary = f"\n\n> 边界提示：{t.boundary_note}" if t.boundary_note else ""

    return f"""
#### 练习（{t.task_type}）

**题目**：{t.prompt}

<details><summary>提示 1（方向性）</summary>

{t.hint_1}

</details>

<details><summary>提示 2（结构性）</summary>

{t.hint_2}

</details>

<details><summary>提示 3（局部操作）</summary>

{t.hint_3}

</details>

**作答区**：请先在此处写下你的完整解答，再展开下方核对。

<details><summary>答案与解析</summary>

**答案**：{t.answer}

**规范解答**：

{t.worked_solution}

**常见错误**：
{errors}

**错误原因**：
{reasons}

</details>

<details><summary>再练一题</summary>

{t.retry_task}
{retry_answer_line}

</details>
{boundary}
""".strip()


def render_tasks_into_good_md(good_md: str, tasks: Sequence[Any]) -> str:
    """
    把 good_md 中的 {{task:<id>}} 占位符替换为 render_task_block(t)。
    未在 tasks 找到的 ID 保留占位符（供 output_gate 拦截）。
    """
    if not good_md:
        return ""

    task_map: dict[str, Any] = {}
    for item in tasks or []:
        tid = getattr(item, "task_id", None) if not isinstance(item, dict) else item.get("task_id")
        if tid is not None:
            task_map[str(tid)] = item

    def _replace(match: re.Match) -> str:
        tid = match.group(1)
        if tid in task_map:
            return render_task_block(task_map[tid])
        return match.group(0)

    return PLACEHOLDER_RE.sub(_replace, good_md)
