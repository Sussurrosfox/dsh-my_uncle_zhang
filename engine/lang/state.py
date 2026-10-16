# -*- coding: utf-8 -*-
"""
lang.state
----------
基于 to_lang.md §2 与 to_upgrade.md §12 的状态与数据对象定义。
"""

from __future__ import annotations
from typing import Annotated, Literal, Optional, Any
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
import operator


# =========================================================================
# to_upgrade.md §12 可复用数据对象
# =========================================================================

class SourceNode(BaseModel):
    """source_node：原教材中的可定位证据"""
    source_id: str
    source_file: str
    page: int
    region: str = ""
    source_quote: str = ""
    transcription: str = ""
    transcription_status: Literal["verified", "uncertain", "disputed"] = "uncertain"
    risk: Literal["formula", "symbol", "figure", "wording", "missing_context", "none"] = "none"
    reviewer: str = ""
    reviewed_at: str = ""


class ConceptNode(BaseModel):
    """concept_node / skill_node / prerequisite / misconception"""
    node_id: str
    kind: Literal["concept", "skill", "prerequisite", "misconception"]
    statement: str
    source_refs: list[str] = Field(default_factory=list)
    observable_evidence: str = ""
    first_use: str = ""                  # 首次使用的单元/小节 ID
    later_uses: list[str] = Field(default_factory=list)
    boundary_or_exception: str = ""


class DependencyEdge(BaseModel):
    """dependency_edge：节点间的前置依赖边"""
    from_id: str                         # 前置节点 ID
    to_id: str                           # 依赖该前置的节点 ID
    relation: Literal[
        "定义所需", "计算所需", "证明所需", "解释所需", "迁移所需",
        "前置依赖", "动机铺垫", "证据支撑", "并列对比", "迁移应用",
        "prerequisite", "builds_on", "proof_support", "explanation", "transfer"
    ] = "定义所需"


class Task(BaseModel):
    """task：练习、分层提示、答案、错因与再练"""
    task_id: str
    unit_id: str
    source_refs: list[str] = Field(default_factory=list)
    objective: str
    task_type: Literal[
        "observe", "classify", "compute", "explain",
        "prove", "model", "transfer", "diagnose"
    ]
    prompt: str
    prerequisite_refs: list[str] = Field(default_factory=list)
    expected_evidence: str               # 可检查的中间产物（不能仅为最终数值）
    answer: str = ""
    worked_solution: str = ""
    common_errors: list[str] = Field(default_factory=list)
    error_reasons: list[str] = Field(default_factory=list)
    hint_1: str = ""                     # 1. 方向提示
    hint_2: str = ""                     # 2. 结构提示
    hint_3: str = ""                     # 3. 局部提示
    retry_task: str = ""                 # 重新尝试或变式任务
    boundary_note: str = ""


class LearningUnit(BaseModel):
    """learning_unit：学习单元能力闭环"""
    unit_id: str
    title: str
    objectives: list[str]                # 可观察动词描述的目标
    completion_criteria: str             # 完成标准
    prerequisite_refs: list[str] = Field(default_factory=list)
    node_refs: list[str] = Field(default_factory=list)
    section_refs: list[str] = Field(default_factory=list)    # 对应原书章节
    good_md_path: str = ""               # 该单元正文在 good.md 中的区段或文件
    status: Literal["planned", "drafted", "gated", "released"] = "planned"
    sections: dict[str, str] = Field(default_factory=dict)   # 单元小节内容字典


class DiagnosisRecord(BaseModel):
    """diagnosis_record：独立阅读审计记录"""
    record_id: str
    section_ref: str
    checkpoint: Literal["goal", "prerequisite", "reasoning", "imitation", "error_location", "transfer"]
    passed: bool
    labels: list[str] = Field(default_factory=list)          # goal_hidden / bridge_missing / ...
    evidence: str = ""                   # 试读者实际说了什么
    severity: Literal["P0", "P1", "P2"] = "P1"
    fix_scope: Literal["正文", "下游互动系统"] = "正文"


class ReviewRecord(BaseModel):
    """review_record：试读与审阅记录"""
    reviewer: str                        # "student_sim:<persona>" / "teacher_rubric" / agent_id
    kind: Literal["student_trial", "teacher_review", "source_check", "regression"]
    target: str                          # unit_id 或 task_id
    findings: list[str] = Field(default_factory=list)
    stuck_points: list[str] = Field(default_factory=list)
    decision: Literal["pass", "revise", "reject"] = "revise"
    created_at: str = ""


class GateResult(BaseModel):
    """gate_result：门禁检查结果"""
    gate: str                            # source / dependency / pedagogy / feedback / ...
    passed: bool
    failures: list[dict[str, Any]] = Field(default_factory=list)
    # failures[i] 示例: {"check": "...", "target": "node_x", "route_to": "structure_rebuilder", "msg": "...", "severity": "P1"}
    decided_by: str = "auto"             # auto | arbiter
    decided_at: str = ""


class ReleaseManifest(BaseModel):
    """release_manifest：版本发布清单与哈希签名"""
    version: str
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_hashes: dict[str, str] = Field(default_factory=dict)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    gate_results: list[GateResult] = Field(default_factory=list)
    approver: str = ""


# =========================================================================
# 状态合并 Reducer 函数
# =========================================================================

def merge_by_key(key: str):
    """
    reducer 工厂：按主键 upsert 合并，供并行分支安全写入同一列表。
    支持 Pydantic 模型实例或 dict。
    """
    def merge(old: list[Any] | None, new: list[Any] | None) -> list[Any]:
        idx: dict[str, Any] = {}
        if old:
            for item in old:
                k = getattr(item, key, None) if not isinstance(item, dict) else item.get(key)
                if k is not None:
                    idx[str(k)] = item
        if new:
            for item in new:
                k = getattr(item, key, None) if not isinstance(item, dict) else item.get(key)
                if k is not None:
                    idx[str(k)] = item
        return list(idx.values())
    return merge


def merge_edges(old: list[DependencyEdge] | None, new: list[DependencyEdge] | None) -> list[DependencyEdge]:
    """
    合并有向依赖边，按 (from_id, to_id, relation) 去重。
    """
    seen = set()
    result = []
    for edge in (old or []):
        key = (edge.from_id, edge.to_id, edge.relation)
        if key not in seen:
            seen.add(key)
            result.append(edge)
    for edge in (new or []):
        key = (edge.from_id, edge.to_id, edge.relation)
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result


def merge_retry_counts(old: dict[str, int] | None, new: dict[str, int] | None) -> dict[str, int]:
    """
    累加/合并 agent 回流重试次数。v <= 0 表示重置归零，v > 0 表示累加。
    """
    counts = dict(old or {})
    for k, v in (new or {}).items():
        if v <= 0:
            counts[k] = 0
        else:
            counts[k] = counts.get(k, 0) + v
    return counts


# =========================================================================
# LangGraph 全局图状态 (GraphState)
# =========================================================================

class GraphState(BaseModel):
    """
    工作流全局图状态。
    所有 agent 只能读写声明的状态字段，产物落盘由状态持久化机制保证。
    """
    # 1. 基础输入
    raw_files: list[str] = Field(default_factory=list)       # 原始教材路径
    discipline: str = "math"                                 # 学科，用于加载学科扩展配置

    # 2. 阶段核心产物
    sources: Annotated[list[SourceNode], merge_by_key("source_id")] = Field(default_factory=list)
    diagnoses: Annotated[list[DiagnosisRecord], merge_by_key("record_id")] = Field(default_factory=list)
    nodes: Annotated[list[ConceptNode], merge_by_key("node_id")] = Field(default_factory=list)
    edges: Annotated[list[DependencyEdge], merge_edges] = Field(default_factory=list)
    units: Annotated[list[LearningUnit], merge_by_key("unit_id")] = Field(default_factory=list)
    tasks: Annotated[list[Task], merge_by_key("task_id")] = Field(default_factory=list)
    reviews: Annotated[list[ReviewRecord], operator.add] = Field(default_factory=list)

    # 3. 正文
    good_md: str = ""                                        # good.md 完整正文
    good_md_path: str = "good.md"

    # 4. 门禁与流转控制
    current_stage: str = "sg1_source"
    gate_results: Annotated[list[GateResult], operator.add] = Field(default_factory=list)
    retry_counts: Annotated[dict[str, int], merge_retry_counts] = Field(default_factory=dict)
    stop_flag: Optional[str] = None                          # 触发停止条件时置位（例如 "P0_stop" 或 arbiter 判定）
    manifest: Optional[ReleaseManifest] = None

    # 5. 消息与交互踪迹
    messages: Annotated[list, add_messages] = Field(default_factory=list)
