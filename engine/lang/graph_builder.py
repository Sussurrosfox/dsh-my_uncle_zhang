# -*- coding: utf-8 -*-
"""
lang.graph_builder
------------------
主图 (MainGraph) 装配、门禁强制路由、熔断仲裁、stale 传播与停止条件实现。
对应 to_lang.md §1, §4.3, §5.6, §6。
"""

from __future__ import annotations
import hashlib
import os
import datetime
from typing import Any, Callable
from langgraph.graph import StateGraph, START, END

from lang.state import (
    GraphState, GateResult, ReleaseManifest,
    SourceNode, ConceptNode, Task, LearningUnit
)
from lang.node_factory import (
    make_agent_node, make_gate_node, load_agents_registry, latest_gate_result
)
from lang.gates.base import Gate
from lang.gates.registry import GATES, GATES_BY_NAME, GATE_SETTINGS, get_gate
from lang.subgraphs.sg1_source import build_sg1_subgraph
from lang.subgraphs.sg2_diagnosis import build_sg2_subgraph
from lang.subgraphs.sg3_structure import build_sg3_subgraph
from lang.subgraphs.sg4_pedagogy import build_sg4_subgraph
from lang.subgraphs.sg5_feedback import build_sg5_subgraph


# =========================================================================
# 6.2 stale 传播实现
# =========================================================================

ALL_GATE_NAMES = [
    "source_gate",
    "diagnosis_gate",
    "dependency_gate",
    "pedagogy_gate",
    "feedback_gate",
    "student_trial_gate",
    "output_gate",
    # 注意：不给 version_gate 追加 stale 记录。
]


def mark_stale(state: GraphState, reason: str = "上游变更", affected_gates: list | None = None) -> dict[str, Any]:
    """上游内容变更后的全量失效。
    - 作废已签发 manifest（出口闸门 export_check 会重新校验）
    - 向受影响 gate 追加显式失败记录，引导 router 走重验/修复回路
    """
    from datetime import datetime, timezone
    from lang.snapshot import compute_state_hash, compute_artifact_hashes
    from lang.state import GateResult

    gates = affected_gates or ALL_GATE_NAMES
    now = datetime.now(timezone.utc).isoformat()
    reason_str = reason if isinstance(reason, str) else f"来源已变更: {reason}"
    stale_results = [
        GateResult(
            gate=g,
            passed=False,
            failures=[{
                "check": "mark_stale",
                "target": g,
                "route_to": "default",
                "msg": f"上游变更，需重新验证: {reason_str}",
                "severity": "P1"
            }],
            decided_by="auto:stale",
            decided_at=now,
            build_id=getattr(state, "build_id", ""),
            state_hash=compute_state_hash(state),
            artifact_hashes=compute_artifact_hashes(state),
        )
        for g in gates
    ]
    return {"gate_results": stale_results, "manifest": None}


# =========================================================================
# 节点实现：release_manager 与 stop_and_report
# =========================================================================

def release_manager_node(state: GraphState) -> dict[str, Any]:
    """
    版本签发节点：
    汇总全部 gate_results、复算输入输出哈希，签发 release_manifest。
    """
    from lang.snapshot import compute_state_hash, RULESET_VERSION, EXECUTOR_VERSION
    from lang.gates.deterministic import validate_gates_current, REQUIRED_GATES
    from lang.state import ReleaseManifest

    # 硬边界：发布前最后一次全量校验。任何一项不过 → 拒绝签发。
    failures = validate_gates_current(state)
    if failures:
        return {"stop_flag": "release_blocked: " + "; ".join(failures)}

    current = compute_state_hash(state)
    build = getattr(state, "build_id", "")

    # 1. 计算输入原始文件哈希
    input_hashes = {}
    for raw_f in state.raw_files:
        if os.path.exists(raw_f):
            try:
                with open(raw_f, "rb") as f:
                    input_hashes[raw_f] = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                input_hashes[raw_f] = "read_error"
        else:
            input_hashes[raw_f] = hashlib.sha256(raw_f.encode("utf-8")).hexdigest()

    # 2. 计算输出文本哈希
    output_hashes = {
        state.good_md_path: hashlib.sha256(state.good_md.encode("utf-8")).hexdigest()
    }

    # 3. 记录工具链版本
    import importlib.metadata
    import pydantic
    try:
        lg_ver = importlib.metadata.version("langgraph")
    except Exception:
        lg_ver = "unknown"
    tool_versions = {
        "langgraph": lg_ver,
        "pydantic": getattr(pydantic, "__version__", "unknown"),
        "ruleset_version": RULESET_VERSION,
        "executor_version": EXECUTOR_VERSION,
        "pipeline_version": "2.0.0"
    }

    final_results = []
    for gate_name in REQUIRED_GATES + ["version_gate"]:
        valid = [
            r for r in state.gate_results
            if r.gate == gate_name and getattr(r, "build_id", "") == build
            and getattr(r, "state_hash", "") == current and r.passed
        ]
        if valid:
            final_results.append(valid[-1])

    manifest = ReleaseManifest(
        version=f"v2.0.0-{current[:8]}",
        build_id=build,
        state_hash=current,
        input_hashes=input_hashes,
        output_hashes=output_hashes,
        tool_versions=tool_versions,
        gate_results=final_results,
        approver="release_manager:auto"
    )

    return {"manifest": manifest}


def task_render_node(state: GraphState) -> dict[str, Any]:
    """正文占位符渲染节点：将 {{task:<id>}} 渲染为结构化自学练习区块"""
    from lang.task_renderer import render_tasks_into_good_md
    return {"good_md": render_tasks_into_good_md(state.good_md, state.tasks)}


def stop_and_report_node(state: GraphState) -> dict[str, Any]:
    """
    保守停止节点 (to_lang.md §6.3, §15):
    触发停止条件或熔断仲裁后调用。输出完整诊断报告，直接走向 END，绝不产出 release_manifest。
    """
    report_lines = [
        "==================================================",
        " [STOP & REPORT] 触发安全停止条件，流水线终止发布",
        "==================================================",
        f"停止原因 (stop_flag): {state.stop_flag or '门禁检出致命结构性缺陷 (P0_stop)'}",
        f"重试统计 (retry_counts): {state.retry_counts}",
        "--- 最近门禁失败详情 ---"
    ]

    latest = state.gate_results[-1] if state.gate_results else None
    if latest:
        report_lines.append(f"门禁: {latest.gate} | 通过状态: {latest.passed}")
        for idx, f in enumerate(latest.failures, 1):
            report_lines.append(f"  [{idx}] 检查项: {f.get('check')} | 目标: {f.get('target')} | 消息: {f.get('msg')}")

    report_lines.append("==================================================")
    print("\n".join(report_lines))

    # 绝不产出 manifest
    return {"stop_flag": state.stop_flag or "stopped"}


# =========================================================================
# 门禁条件路由器工厂 (to_lang.md §4.3)
# =========================================================================

def make_gate_router(gate: Gate, max_retry: int = 3) -> Callable[[GraphState], str]:
    """
    根据 GateResult 判定下一跳：
    1. 若已有 stop_flag 或检出 P0_stop -> 立即走向 'stop_and_report'；
    2. 若未通过 -> 查门禁 route_table 得到修复目标 agent：
       - 若该 agent 重试次数 >= max_retry -> 走向 'arbiter' 做终局熔断仲裁；
       - 否则 -> 强制路由到具体修复 agent；
    3. 若通过 -> 走向 gate.next_stage。
    """
    def router(state: GraphState) -> str:
        if state.stop_flag:
            return "stop_and_report"

        result = latest_gate_result(state, gate.name)
        if not result:
            return gate.next_stage

        # 检查是否触发 P0 级严重结构性失败
        if any(f.get("severity") == "P0_stop" for f in result.failures):
            return "stop_and_report"

        if not result.passed:
            # 获取失败首选路由类别
            fail_category = result.failures[0].get("route_to", "default")
            target_agent = gate.route_table.get(fail_category, gate.route_table.get("default", "writer"))

            # 熔断检查
            if state.retry_counts.get(target_agent, 0) >= max_retry:
                return "arbiter"

            return target_agent

        return gate.next_stage

    return router


def make_arbiter_router() -> Callable[[GraphState], str]:
    """仲裁结果条件路由：若是停止则走 stop_and_report，若需全量重验证则走 sg1_source，否则走重排单元 unit_designer"""
    def router(state: GraphState) -> str:
        if state.stop_flag:
            return "stop_and_report"
        from lang.gates.deterministic import validate_gates_current
        errs = validate_gates_current(state, include_version_gate=False)
        early_gates = ["source_gate", "diagnosis_gate", "dependency_gate"]
        if any(any(eg in e for eg in early_gates) for e in errs):
            return "sg1_source"
        return "unit_designer"
    return router


# =========================================================================
# 主图组装器 (MainGraph Assembly)
# =========================================================================

def build_main_graph(
    registry: dict = None,
    max_retry: int = 3,
    use_compiled_subgraphs: bool = True
) -> StateGraph:
    """
    组装完整的 MainGraph。
    严格实施 to_lang.md §1 架构图拓扑与全量门禁强制调用。
    """
    if not registry:
        registry = load_agents_registry()

    g = StateGraph(GraphState)

    # 1. 注册 SG1 - SG5 阶段节点（子图形态编译挂入）
    if use_compiled_subgraphs:
        sg1 = build_sg1_subgraph(registry, max_retry=max_retry).compile()
        sg2 = build_sg2_subgraph(registry, max_retry=max_retry).compile()
        sg3 = build_sg3_subgraph(registry, max_retry=max_retry).compile()
        sg4 = build_sg4_subgraph(registry, max_retry=max_retry).compile()
        sg5 = build_sg5_subgraph(registry, max_retry=max_retry).compile()

        g.add_node("sg1_source", sg1)
        g.add_node("sg2_diagnosis", sg2)
        g.add_node("sg3_structure", sg3)
        g.add_node("sg4_pedagogy", sg4)
        g.add_node("sg5_feedback", sg5)
    else:
        # 单节点平铺测试形态
        g.add_node("sg1_source", make_agent_node("evidence_builder", registry))
        g.add_node("sg2_diagnosis", make_agent_node("reading_auditor", registry))
        g.add_node("sg3_structure", make_agent_node("structure_rebuilder", registry))
        g.add_node("sg4_pedagogy", make_agent_node("writer", registry))
        g.add_node("sg5_feedback", make_agent_node("task_author", registry))

    # 2. 注册主图测试与发布阶段节点
    g.add_node("task_render", task_render_node)
    g.add_node("student_simulator", make_agent_node("student_simulator", registry))
    g.add_node("release_manager", release_manager_node)
    g.add_node("stop_and_report", stop_and_report_node)
    g.add_node("arbiter", make_agent_node("arbiter", registry))

    # 3. 注册所有具备独立修复能力的 Agent 节点（供全局回流调用）
    raw_evidence_fixer = make_agent_node("evidence_fixer", registry)

    def evidence_fixer_node(state: GraphState, config=None) -> dict[str, Any]:
        patch = raw_evidence_fixer(state, config) if config is not None else raw_evidence_fixer(state)
        repaired_sources = patch.get("sources", [])
        repaired_ids = [
            (s.source_id if hasattr(s, "source_id") else s.get("source_id"))
            for s in repaired_sources
        ]
        repaired_ids = [sid for sid in repaired_ids if sid]
        if repaired_ids:
            stale_patch = mark_stale(state, reason=f"evidence_fixer 修复来源: {repaired_ids}")
            if "gate_results" in stale_patch:
                patch["gate_results"] = list(patch.get("gate_results", [])) + stale_patch["gate_results"]
            if "manifest" in stale_patch:
                patch["manifest"] = stale_patch["manifest"]
        return patch

    g.add_node("evidence_fixer", evidence_fixer_node)
    g.add_node("reading_auditor", make_agent_node("reading_auditor", registry))
    g.add_node("structure_rebuilder", make_agent_node("structure_rebuilder", registry))
    g.add_node("unit_designer", make_agent_node("unit_designer", registry))
    g.add_node("writer", make_agent_node("writer", registry))
    g.add_node("task_author", make_agent_node("task_author", registry))
    g.add_node("converter_fixer", make_agent_node("converter_fixer", registry))

    # 4. 注册主图层级的全量 Gate 节点
    for gate_name in [
        "source_gate", "diagnosis_gate", "dependency_gate",
        "pedagogy_gate", "feedback_gate", "student_trial_gate",
        "output_gate", "version_gate"
    ]:
        gate_obj = get_gate(gate_name)
        g.add_node(f"gate_{gate_name}", make_gate_node(gate_obj))

    # 5. 编排主拓扑顺序边
    g.add_edge(START, "sg1_source")
    g.add_edge("sg1_source", "gate_source_gate")

    # 修复 agent 完成后重新进入对应门禁核验
    g.add_edge("evidence_fixer", "gate_source_gate")
    g.add_edge("reading_auditor", "gate_diagnosis_gate")
    g.add_edge("structure_rebuilder", "gate_dependency_gate")
    g.add_edge("unit_designer", "gate_pedagogy_gate")
    g.add_edge("writer", "gate_pedagogy_gate")
    g.add_edge("task_author", "gate_feedback_gate")
    g.add_edge("converter_fixer", "gate_output_gate")

    # stop_and_report 走向终止
    g.add_edge("stop_and_report", END)
    # release_manager 走向终止
    g.add_edge("release_manager", END)

    # 6. 配置门禁条件路由边（强制调用核心机制）

    # gate_source_gate
    gate_src = get_gate("source_gate")
    gate_src.next_stage = "sg2_diagnosis"
    g.add_conditional_edges(
        "gate_source_gate",
        make_gate_router(gate_src, max_retry=max_retry),
        {
            "evidence_fixer": "evidence_fixer",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "sg2_diagnosis": "sg2_diagnosis"
        }
    )
    g.add_edge("sg2_diagnosis", "gate_diagnosis_gate")

    # gate_diagnosis_gate
    gate_diag = get_gate("diagnosis_gate")
    gate_diag.next_stage = "sg3_structure"
    g.add_conditional_edges(
        "gate_diagnosis_gate",
        make_gate_router(gate_diag, max_retry=max_retry),
        {
            "reading_auditor": "reading_auditor",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "sg3_structure": "sg3_structure"
        }
    )
    g.add_edge("sg3_structure", "gate_dependency_gate")

    # gate_dependency_gate
    gate_dep = get_gate("dependency_gate")
    gate_dep.next_stage = "sg4_pedagogy"
    g.add_conditional_edges(
        "gate_dependency_gate",
        make_gate_router(gate_dep, max_retry=max_retry),
        {
            "structure_rebuilder": "structure_rebuilder",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "sg4_pedagogy": "sg4_pedagogy"
        }
    )
    g.add_edge("sg4_pedagogy", "gate_pedagogy_gate")

    # gate_pedagogy_gate
    gate_ped = get_gate("pedagogy_gate")
    gate_ped.next_stage = "sg5_feedback"
    g.add_conditional_edges(
        "gate_pedagogy_gate",
        make_gate_router(gate_ped, max_retry=max_retry),
        {
            "writer": "writer",
            "unit_designer": "unit_designer",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "sg5_feedback": "sg5_feedback"
        }
    )
    g.add_edge("sg5_feedback", "gate_feedback_gate")

    # gate_feedback_gate
    gate_fb = get_gate("feedback_gate")
    gate_fb.next_stage = "task_render"
    g.add_conditional_edges(
        "gate_feedback_gate",
        make_gate_router(gate_fb, max_retry=max_retry),
        {
            "task_author": "task_author",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "task_render": "task_render"
        }
    )
    g.add_edge("task_render", "student_simulator")
    g.add_edge("student_simulator", "gate_student_trial_gate")

    # gate_student_trial_gate
    gate_trial = get_gate("student_trial_gate")
    gate_trial.next_stage = "gate_output_gate"
    g.add_conditional_edges(
        "gate_student_trial_gate",
        make_gate_router(gate_trial, max_retry=max_retry),
        {
            "structure_rebuilder": "structure_rebuilder",
            "writer": "writer",
            "task_author": "task_author",
            "unit_designer": "unit_designer",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "gate_output_gate": "gate_output_gate"
        }
    )

    # gate_output_gate
    gate_out = get_gate("output_gate")
    gate_out.next_stage = "gate_version_gate"
    g.add_conditional_edges(
        "gate_output_gate",
        make_gate_router(gate_out, max_retry=max_retry),
        {
            "converter_fixer": "converter_fixer",
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "gate_version_gate": "gate_version_gate"
        }
    )

    # gate_version_gate
    gate_ver = get_gate("version_gate")
    gate_ver.next_stage = "release_manager"
    g.add_conditional_edges(
        "gate_version_gate",
        make_gate_router(gate_ver, max_retry=max_retry),
        {
            "arbiter": "arbiter",
            "stop_and_report": "stop_and_report",
            "release_manager": "release_manager"
        }
    )

    # arbiter 仲裁条件边
    g.add_conditional_edges(
        "arbiter",
        make_arbiter_router(),
        {
            "stop_and_report": "stop_and_report",
            "unit_designer": "unit_designer",
            "sg1_source": "sg1_source"
        }
    )

    return g
