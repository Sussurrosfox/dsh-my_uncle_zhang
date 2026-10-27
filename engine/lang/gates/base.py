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
from typing import Callable, Any, Optional, Union
from pydantic import BaseModel, Field, ConfigDict
from lang.state import GraphState, GateResult


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


GateCheckFunc = Callable[[GraphState], Union[list[dict[str, Any]], CheckFailures]]


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
        结果注入构建快照绑定（阶段 A）：build_id / state_hash / 版本戳。
        """
        from datetime import datetime, timezone
        from lang.snapshot import (
            RULESET_VERSION, EXECUTOR_VERSION,
            compute_state_hash, compute_artifact_hashes,
        )
        started = datetime.now(timezone.utc).isoformat()
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

        finished = datetime.now(timezone.utc).isoformat()
        passed = (len(all_failures) == 0)

        return GateResult(
            gate=self.name,
            passed=passed,
            failures=all_failures,
            decided_by="auto",
            decided_at=finished,
            build_id=getattr(state, "build_id", ""),
            state_hash=compute_state_hash(state),
            artifact_hashes=compute_artifact_hashes(state),
            ruleset_version=RULESET_VERSION,
            executor_version=EXECUTOR_VERSION,
            started_at=started,
            finished_at=finished,
        )
