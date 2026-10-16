# -*- coding: utf-8 -*-
"""
lang.gates.base
---------------
门禁系统基础抽象与评估器。
门禁是图拓扑的组成部分，不是单纯的提示词。
每个门禁 = 一组确定性检查（代码可判定）+ 可选 LLM rubric 评审。
产出 GateResult，自身不修改任何内容产物。
"""

from __future__ import annotations
import datetime
from typing import Callable, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from lang.state import GraphState, GateResult


GateCheckFunc = Callable[[GraphState], list[dict[str, Any]]]


class Gate(BaseModel):
    """门禁定义"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""
    checks: list[GateCheckFunc] = Field(default_factory=list)
    rubric: Optional[str] = None
    route_table: dict[str, str] = Field(default_factory=dict)
    next_stage: str = "END"

    def evaluate(self, state: GraphState, rubric_evaluator: Optional[Callable[[GraphState, str], list[dict]]] = None) -> GateResult:
        """
        执行当前门禁的全量检查。
        先执行确定性代码检查，若配置了 rubric 且提供评审器，则执行补充评审。
        """
        all_failures: list[dict[str, Any]] = []

        # 1. 确定性检查（代码判定）
        for check in self.checks:
            try:
                failures = check(state)
                if failures:
                    all_failures.extend(failures)
            except Exception as e:
                all_failures.append({
                    "check": getattr(check, "__name__", "unknown_check"),
                    "target": self.name,
                    "route_to": "default",
                    "msg": f"门禁检查执行异常: {str(e)}",
                    "severity": "P1"
                })

        # 2. 可选 LLM rubric 辅助评审
        if self.rubric and rubric_evaluator and not any(f.get("severity") == "P0_stop" for f in all_failures):
            try:
                rubric_failures = rubric_evaluator(state, self.rubric)
                if rubric_failures:
                    all_failures.extend(rubric_failures)
            except Exception as e:
                # 辅助评审异常不阻塞，但记录为 P2 警告
                all_failures.append({
                    "check": "rubric_evaluator",
                    "target": self.name,
                    "route_to": "default",
                    "msg": f"LLM Rubric 辅助评审异常: {str(e)}",
                    "severity": "P2"
                })

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        passed = (len(all_failures) == 0)

        return GateResult(
            gate=self.name,
            passed=passed,
            failures=all_failures,
            decided_by="auto",
            decided_at=now_str
        )
