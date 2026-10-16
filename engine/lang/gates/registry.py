# -*- coding: utf-8 -*-
"""
lang.gates.registry
-------------------
门禁注册与配置装配模块。
从 gates.yaml 中加载门禁元数据，并将检查函数字符串绑定到 deterministic.py 中的实现。
"""

from __future__ import annotations
import os
import yaml
from typing import Callable, Any
from lang.gates.base import Gate
from lang.gates import deterministic as det_checks


# 检查函数名称 -> 实际函数对象映射
CHECK_MAPPING: dict[str, Callable] = {
    # 来源门禁
    "check_all_sources_verified": det_checks.check_all_sources_verified,
    "check_high_risk_reviewed": det_checks.check_high_risk_reviewed,
    "check_risks_have_actions": det_checks.check_risks_have_actions,

    # 诊断门禁
    "check_diagnoses_non_empty": det_checks.check_diagnoses_non_empty,
    "check_diagnosis_evidence_and_scope": det_checks.check_diagnosis_evidence_and_scope,
    "check_no_vague_reasons": det_checks.check_no_vague_reasons,

    # 依赖门禁
    "check_graph_acyclic": det_checks.check_graph_acyclic,
    "check_dependencies_closure": det_checks.check_dependencies_closure,
    "check_no_dangling_references": det_checks.check_no_dangling_references,

    # 教学门禁
    "check_minimal_unit_sections": det_checks.check_minimal_unit_sections,
    "check_observable_objectives": det_checks.check_observable_objectives,
    "check_no_obvious_step_skips": det_checks.check_no_obvious_step_skips,

    # 反馈门禁
    "check_tasks_required_fields": det_checks.check_tasks_required_fields,
    "check_layered_hints": det_checks.check_layered_hints,
    "check_expected_evidence_validity": det_checks.check_expected_evidence_validity,

    # 试读门禁
    "check_trial_coverage": det_checks.check_trial_coverage,
    "check_no_stagnation": det_checks.check_no_stagnation,
    "check_review_decisions": det_checks.check_review_decisions,

    # 输出门禁
    "check_good_md_non_empty": det_checks.check_good_md_non_empty,
    "check_formula_conservation": det_checks.check_formula_conservation,

    # 版本门禁
    "check_all_gates_passed": det_checks.check_all_gates_passed,
    "check_hash_integrity": det_checks.check_hash_integrity,
    "check_task_bank_export_consistency": det_checks.check_task_bank_export_consistency,
}


def load_gates_config(config_path: str = "") -> dict[str, Any]:
    """加载 gates.yaml 配置文件"""
    if not config_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config", "gates.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"未找到门禁配置文件: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_gates(config_path: str = "") -> tuple[list[Gate], dict[str, Any]]:
    """构建 Gate 对象列表和全局设置"""
    raw_cfg = load_gates_config(config_path)
    settings = raw_cfg.get("settings", {"max_retry": 3, "stop_on_p0": True})
    gates_data = raw_cfg.get("gates", {})

    gates_list = []
    for g_id, g_spec in gates_data.items():
        check_funcs = []
        for c_name in g_spec.get("checks", []):
            if c_name in CHECK_MAPPING:
                check_funcs.append(CHECK_MAPPING[c_name])
            else:
                print(f"[Warning] 未找到检查函数映射: {c_name}")

        gate_obj = Gate(
            name=g_spec.get("name", g_id),
            description=g_spec.get("description", ""),
            checks=check_funcs,
            rubric=g_spec.get("rubric"),
            route_table=g_spec.get("route_table", {}),
            next_stage=g_spec.get("next_stage", "END")
        )
        gates_list.append(gate_obj)

    return gates_list, settings


# 预初始化全局门禁
GATES, GATE_SETTINGS = build_gates()
GATES_BY_NAME = {g.name: g for g in GATES}


def get_gate(name: str) -> Gate:
    """根据门禁名称获取 Gate 对象"""
    if name not in GATES_BY_NAME:
        raise KeyError(f"未知的门禁名称: {name} (可用门禁: {list(GATES_BY_NAME.keys())})")
    return GATES_BY_NAME[name]
