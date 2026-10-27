# -*- coding: utf-8 -*-
"""
lang.exporters
--------------
最小可交付包落盘与 export_check 机械校验 (to_lang.md §13)
"""

from __future__ import annotations
import json
import os
import hashlib
from typing import Any
from lang.state import GraphState, ReleaseManifest
from lang.snapshot import compute_state_hash
from lang.gates.deterministic import validate_gates_current


class ExportVerificationError(Exception):
    """导出校验异常：当 manifest 不合法或输出哈希不匹配时阻断写盘"""
    pass


def compute_content_sha256(content: str | bytes) -> str:
    """计算文本或字节的 SHA256"""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _ensure_state_obj(state: GraphState | dict[str, Any]) -> GraphState:
    """将 dict 统一转为 GraphState 实例"""
    if isinstance(state, GraphState):
        return state
    return GraphState(**state)


def export_check(state: GraphState | dict[str, Any]) -> None:
    """
    to_lang.md §13 导出前置校验：
    1. 确认 state.manifest 不为空且快照一致；
    2. 校验所有门禁有效性；
    3. 确认所有必须文件均有数据可写。
    """
    st = _ensure_state_obj(state)
    m = st.manifest
    if m is None:
        raise ExportVerificationError("无 manifest，拒绝导出")

    errors: list[str] = []
    current = compute_state_hash(st)

    if getattr(m, "state_hash", "") != current:
        errors.append("manifest.state_hash 与当前内容快照不一致")
    if getattr(m, "build_id", "") != getattr(st, "build_id", ""):
        errors.append("manifest.build_id 与 state.build_id 不一致")

    errors.extend(validate_gates_current(st))

    for r in m.gate_results:
        if not r.passed:
            errors.append(f"manifest 内含未通过记录: {r.gate}")
        if getattr(r, "state_hash", "") != current:
            errors.append(f"manifest 内 {r.gate} 记录快照过期")
        if getattr(r, "build_id", "") != getattr(st, "build_id", ""):
            errors.append(f"manifest 内 {r.gate} 记录跨构建")

    # 保留原有对 good_md / nodes / tasks 的非空检查
    if not getattr(m, "approver", "").strip():
        errors.append("state.manifest.approver 字段无效！")
    if not st.good_md or not st.good_md.strip():
        errors.append("state.good_md 为空，无有效教材正文！")
    if not st.nodes:
        errors.append("state.nodes 为空，概念图数据缺失！")
    if not st.tasks:
        errors.append("state.tasks 为空，任务题库缺失！")
    if not st.gate_results:
        errors.append("state.gate_results 为空，门禁报告缺失！")

    if errors:
        raise ExportVerificationError("; ".join(errors))


def export_all(state: GraphState | dict[str, Any], output_dir: str) -> dict[str, str]:
    """
    将流水线最终状态一次性落地为最小可交付包：
    ├── good.md                  # 终版自学教材（必须通过所有门禁）
    ├── graph.json               # 概念图拓扑：{nodes: [...], edges: [...]}
    ├── tasks.json               # 题库：所有 Task 对象的序列化
    ├── evidence_manifest.json   # 证据清单：所有 SourceNode 的完整信息
    ├── diagnosis_report.md      # 诊断报告：合并后的非结构化诊断记录
    ├── trial_report.md          # 试读报告：三个 persona 的试读记录与修复记录
    ├── release_manifest.json    # 发布清单：版本、哈希、门禁通过证明
    └── gate_reports/            # 各门禁的独立检验报告
        ├── source_gate.json
        ├── diagnosis_gate.json
        ├── ...

    返回产出文件及其 SHA256 字典。
    """
    # 1. 前置强校验
    export_check(state)
    st = _ensure_state_obj(state)

    os.makedirs(output_dir, exist_ok=True)
    gate_reports_dir = os.path.join(output_dir, "gate_reports")
    os.makedirs(gate_reports_dir, exist_ok=True)

    written_files: dict[str, str] = {}

    def _write_text(filename: str, content: str) -> str:
        fpath = os.path.join(output_dir, filename)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        sha = compute_content_sha256(content)
        written_files[fpath] = sha
        return sha

    def _write_json(filename: str, data: Any) -> str:
        fpath = os.path.join(output_dir, filename)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        sha = compute_content_sha256(content)
        written_files[fpath] = sha
        return sha

    # 2. 写入 good.md
    good_md_sha = _write_text("good.md", st.good_md)

    # 3. 写入 graph.json
    graph_dict = {
        "nodes": [n.model_dump() for n in st.nodes],
        "edges": [e.model_dump() for e in st.edges]
    }
    _write_json("graph.json", graph_dict)

    # 4. 写入 tasks.json
    tasks_list = [t.model_dump() for t in st.tasks]
    _write_json("tasks.json", tasks_list)

    # 5. 写入 evidence_manifest.json
    evidence_list = [s.model_dump() for s in st.sources]
    _write_json("evidence_manifest.json", evidence_list)

    # 6. 写入 diagnosis_report.md
    diag_lines = ["# 教材防自学诊断报告\n"]
    for d in st.diagnoses:
        diag_lines.append(f"## 位置/章节: {d.section_ref}")
        diag_lines.append(f"- **检查项**: {d.checkpoint} | **通过**: {d.passed}")
        diag_lines.append(f"- **严重级别**: {d.severity}")
        diag_lines.append(f"- **缺陷证据**: {d.evidence}")
        diag_lines.append(f"- **整改范围**: {d.fix_scope}")
        diag_lines.append(f"- **标签**: {', '.join(d.labels)}\n")
    _write_text("diagnosis_report.md", "\n".join(diag_lines))

    # 7. 写入 trial_report.md
    trial_lines = ["# 学生模拟试读与同行评审报告\n"]
    for r in st.reviews:
        trial_lines.append(f"## 评审者: {r.reviewer} ({r.kind})")
        trial_lines.append(f"- **决策**: {r.decision}")
        trial_lines.append(f"- **目标**: {r.target}")
        trial_lines.append(f"- **卡点/问题**: {', '.join(r.stuck_points)}")
        trial_lines.append(f"- **评审意见**: {', '.join(r.findings)}\n")
    _write_text("trial_report.md", "\n".join(trial_lines))

    # 8. 写入各门禁独立报告 gate_reports/<gate_name>.json
    for gr in st.gate_results:
        gr_path = os.path.join(gate_reports_dir, f"{gr.gate}.json")
        gr_content = json.dumps(gr.model_dump(), ensure_ascii=False, indent=2)
        with open(gr_path, "w", encoding="utf-8") as f:
            f.write(gr_content)
        written_files[gr_path] = compute_content_sha256(gr_content)

    # 9. 写入 release_manifest.json
    manifest_dict = st.manifest.model_dump() if st.manifest else {}
    _write_json("release_manifest.json", manifest_dict)

    # 10. 写入 state.json (供离线门禁独立审计)
    _write_json("state.json", st.model_dump())

    # 11. 后置强校验：确认 good.md 哈希与 manifest 一致
    expected_good_md_sha = st.manifest.output_hashes.get(st.good_md_path)
    if expected_good_md_sha and expected_good_md_sha != good_md_sha:
        raise ExportVerificationError(
            f"写入后 good.md SHA256 ({good_md_sha}) 与 manifest 登记的哈希 ({expected_good_md_sha}) 不匹配！"
        )

    return written_files
