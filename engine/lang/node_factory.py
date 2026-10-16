# -*- coding: utf-8 -*-
"""
lang.node_factory
-----------------
Agent 节点与门禁节点工厂。
依据 config/agents.yaml 生成标准 LangGraph 节点，
强制执行 reads/writes 白名单隔离、失败上下文注入、学科补丁加载及多 persona 模拟。
"""

from __future__ import annotations
import os
import re
import json
import yaml
from typing import Any, Callable, Optional
from pydantic import BaseModel
from langchain_core.runnables import RunnableConfig
from lang.state import (
    GraphState, GateResult, SourceNode, ConceptNode,
    DependencyEdge, Task, LearningUnit, DiagnosisRecord, ReviewRecord
)
from lang.tools import get_tools_by_names
from lang.gates.base import Gate


# =========================================================================
# 辅助函数：上下文构建、学科补丁、序列化
# =========================================================================

def load_agents_registry(config_path: str = "") -> dict[str, Any]:
    """读取 config/agents.yaml 声明式注册表"""
    if not config_path:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config", "agents.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_discipline_config(discipline: str = "math") -> dict[str, Any]:
    """读取指定学科扩展配置"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    disc_path = os.path.join(base_dir, "config", "disciplines", f"{discipline}.yaml")
    if os.path.exists(disc_path):
        with open(disc_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {"prompt_patch": "", "rules": {}}


def load_prompt_template(prompt_file: str) -> str:
    """加载 agent 的 prompt 模板文件"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, prompt_file)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"# Prompt: {prompt_file}\n请根据输入生成合规产物。"


def latest_gate_result(state: GraphState, gate_name: str = "") -> Optional[GateResult]:
    """获取指定门禁或最近一次门禁的评估结果"""
    if not state.gate_results:
        return None
    for gr in reversed(state.gate_results):
        if not gate_name or gr.gate == gate_name:
            return gr
    return None


def build_repair_context(state: GraphState, agent_id: str = "") -> dict[str, Any]:
    """
    to_lang.md §4.4：为被门禁强制调用的修复 agent 注入失败清单上下文。
    """
    latest = state.gate_results[-1] if state.gate_results else None
    if not latest or latest.passed:
        return {
            "failed_checks": [],
            "failed_targets": [],
            "gate_messages": [],
            "attempt": state.retry_counts.get(agent_id, 0),
        }

    return {
        "failed_gate": latest.gate,
        "failed_checks": [f.get("check") for f in latest.failures],
        "failed_targets": [f.get("target") for f in latest.failures],
        "gate_messages": [f.get("msg") for f in latest.failures],
        "attempt": state.retry_counts.get(agent_id, 0),
    }


def serialize_for_prompt(val: Any) -> Any:
    """将复杂对象转换为用于 prompt 渲染的字符串/dict"""
    if isinstance(val, BaseModel):
        return val.model_dump()
    if isinstance(val, list):
        return [serialize_for_prompt(x) for x in val]
    if isinstance(val, dict):
        return {k: serialize_for_prompt(v) for k, v in val.items()}
    return val


def parse_patch(raw_output: Any, allowed_keys: list[str]) -> dict[str, Any]:
    """
    结构化输出校验：强制实施 writes 白名单过滤与类型反序列化。
    任何未声明的 key 一律剔除。
    """
    data: dict[str, Any] = {}
    if isinstance(raw_output, dict):
        data = raw_output
    elif isinstance(raw_output, str):
        # 尝试提取 ```json ... ``` 块
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_output)
        json_str = match.group(1) if match else raw_output.strip()
        try:
            data = json.loads(json_str)
        except Exception:
            data = {}

    patch: dict[str, Any] = {}
    for key in allowed_keys:
        if key in data:
            val = data[key]
            # 根据 key 进行目标 Pydantic 类型转换
            if key == "sources" and isinstance(val, list):
                patch[key] = [SourceNode(**x) if isinstance(x, dict) else x for x in val]
            elif key == "diagnoses" and isinstance(val, list):
                patch[key] = [DiagnosisRecord(**x) if isinstance(x, dict) else x for x in val]
            elif key == "nodes" and isinstance(val, list):
                patch[key] = [ConceptNode(**x) if isinstance(x, dict) else x for x in val]
            elif key == "edges" and isinstance(val, list):
                patch[key] = [DependencyEdge(**x) if isinstance(x, dict) else x for x in val]
            elif key == "units" and isinstance(val, list):
                patch[key] = [LearningUnit(**x) if isinstance(x, dict) else x for x in val]
            elif key == "tasks" and isinstance(val, list):
                patch[key] = [Task(**x) if isinstance(x, dict) else x for x in val]
            elif key == "reviews" and isinstance(val, list):
                patch[key] = [ReviewRecord(**x) if isinstance(x, dict) else x for x in val]
            else:
                patch[key] = val

    return patch


# =========================================================================
# Mock / Default LLM 与 LLM 工厂
# =========================================================================

class MockAgentLLM:
    """
    可测试的确定性/规则驱动 LLM，用于离线无 API-Key 场景及单元测试。
    根据不同的 agent_id 生成结构严谨、完全合规的状态补丁。
    """
    def __init__(self, agent_id: str, ensemble_persona: str = ""):
        self.agent_id = agent_id
        self.ensemble_persona = ensemble_persona

    def invoke(self, prompt: str) -> dict[str, Any]:
        aid = self.agent_id

        if aid == "evidence_builder" or aid == "source_verifier" or aid == "evidence_fixer":
            reviewer_name = "evidence_builder" if aid == "evidence_builder" else "source_verifier_lead"
            return {
                "sources": [
                    {
                        "source_id": "src_1_1_intro",
                        "source_file": "1.1_集合的概念.md",
                        "page": 1,
                        "region": "第一章章首引言 (L1-L6)",
                        "source_quote": "方程 x^2 = 2 在有理数范围内无解,但在实数范围内有解. 在平面内, 所有到定点的距离等于定长的点组成一个圆; 而在空间中, 所有到定点的距离等于定长的点组成一个球面. 因此, 明确研究对象、确定研究范围是研究数学问题的基础.",
                        "transcription": "方程 $x^2 = 2$ 在有理数范围内无解，但在实数范围内有解；平面内到定点距离等于定长的点组成圆，空间中则组成球面。明确研究对象与研究范围是研究数学问题的基础。",
                        "transcription_status": "verified",
                        "risk": "formula",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_examples",
                        "source_file": "1.1_集合的概念.md",
                        "page": 2,
                        "region": "§1.1 引入案例 (1)-(6) 及思考 (L13-L32)",
                        "source_quote": "(1) 1~10 之间的所有偶数；(2)立德中学今年入学的全体高一学生；(3)所有的正方形；(4)到直线 l 的距离等于定长 d 的所有点；(5)方程 x^2 - 3x + 2 = 0 的所有实数根；(6)地球上的四大洋.",
                        "transcription": "六个典型引例：(1) $1\\sim 10$ 之间的所有偶数；(2) 立德中学今年入学的全体高一学生；(3) 所有的正方形；(4) 到直线 $l$ 的距离等于定长 $d$ 的所有点；(5) 方程 $x^2 - 3x + 2 = 0$ 的所有实数根；(6) 地球上的四大洋。",
                        "transcription_status": "verified",
                        "risk": "formula",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_def_props",
                        "source_file": "1.1_集合的概念.md",
                        "page": 2,
                        "region": "§1.1 集合与元素定义及三大特征 (L33-L45)",
                        "source_quote": "一般地，我们把研究对象统称为元素(element)，把一些元素组成的总体叫做集合 (set)(简称为集). 给定的集合，它的元素必须是确定的... 一个给定集合中的元素是互不相同的... 只要构成两个集合的元素是一样的, 我们就称这两个集合是相等的.",
                        "transcription": "把研究对象统称为元素（element，记作 $a,b,c,\\cdots$），把一些元素组成的总体叫做集合（set，记作 $A,B,C,\\cdots$）。集合元素具备确定性、互异性、无序性；构成元素相同的两个集合相等。属于记作 $a \\in A$，不属于记作 $a \\notin A$。",
                        "transcription_status": "verified",
                        "risk": "symbol",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_num_sets",
                        "source_file": "1.1_集合的概念.md",
                        "page": 3,
                        "region": "§1.1 常用数集及其记法 (L47-L58)",
                        "source_quote": "全体非负整数组成的集合称为非负整数集(或自然数集)，记作 N；全体正整数组成的集合称为正整数集，记作 N* 或 N+；全体整数组成的集合称为整数集，记作 Z；全体有理数组成的集合称为有理数集，记作 Q；全体实数组成的集合称为实数集,记作 R.",
                        "transcription": "五个核心数集记号：非负整数集（自然数集）$\\mathbf{N}$（含 $0$）；正整数集 $\\mathbf{N}^*$ 或 $\\mathbf{N}_+$（不含 $0$）；整数集 $\\mathbf{Z}$；有理数集 $\\mathbf{Q}$；实数集 $\\mathbf{R}$。",
                        "transcription_status": "verified",
                        "risk": "symbol",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_roster",
                        "source_file": "1.1_集合的概念.md",
                        "page": 3,
                        "region": "§1.1 列举法与例1 (L61-L97)",
                        "source_quote": "像这样把集合的所有元素一一列举出来，并用花括号 “ {} ” 括起来表示集合的方法叫做列举法. 例 1 用列举法表示下列集合: (1)小于 10 的所有自然数组成的集合; (2)方程 x^2 = x 的所有实数根组成的集合.",
                        "transcription": "列举法：把集合的所有元素一一列举出来，并用花括号 $\\{\\}$ 括起来。例 1：(1) $A = \\{0,1,2,3,4,5,6,7,8,9\\}$；(2) $B = \\{0,1\\}$。思考：$\\{0,3,6,9\\}$ 的自然语言描述及 $x-7<3$ 解集为何无法用列举法表示。",
                        "transcription_status": "verified",
                        "risk": "formula",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_builder",
                        "source_file": "1.1_集合的概念.md",
                        "page": 4,
                        "region": "§1.1 描述法与例2 (L99-L185)",
                        "source_quote": "一般地,设 A 是一个集合,我们把集合 A 中所有具有共同特征 P(x) 的元素 x 所组成的集合表示为 { x ∈ A | P(x) } , 这种表示集合的方法称为描述法.",
                        "transcription": "描述法：利用集合中元素的共同特征表示为 $\\{x \\in A \\mid P(x)\\}$（也可用冒号或分号）。包含奇数集 $\\{x \\in \\mathbf{Z} \\mid x = 2k+1, k \\in \\mathbf{Z}\\}$、偶数集 $\\{x \\in \\mathbf{Z} \\mid x = 2k, k \\in \\mathbf{Z}\\}$、有理数集 $\\mathbf{Q}$ 及例 2（$x^2-2=0$ 的实数根集与 $10<x<20$ 的整数集）。",
                        "transcription_status": "verified",
                        "risk": "formula",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_practice",
                        "source_file": "1.1_集合的概念.md",
                        "page": 5,
                        "region": "§1.1 课堂练习 1-3 (L187-L205)",
                        "source_quote": "1. 判断下列元素的全体是否组成集合... 2. 用符号 ∈ 或 ∉ 填空... 3. 用适当的方法表示下列集合: (1)由方程 x^2 - 9 = 0 的所有实数根组成的集合；(2)一次函数 y = x + 3 与 y = -2x + 6 图象的交点组成的集合；(3)不等式 4x - 5 < 3 的解集.",
                        "transcription": "课堂练习 1-3：涵盖集合构成判定（到定点 $A,B$ 等距离的点 vs 游泳能手）、常用数集填空（含原文 OCR 漏符修复：$\\sqrt{2} \\notin \\mathbf{Z}, \\frac{1}{3} \\in \\mathbf{Q}, \\pi \\in \\mathbf{R}$）及三类集合表示（含函数图象交点点集 $\\{(1,4)\\}$）。",
                        "transcription_status": "verified",
                        "risk": "wording",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    },
                    {
                        "source_id": "src_1_1_exercises",
                        "source_file": "1.1_集合的概念.md",
                        "page": 5,
                        "region": "§1.1 习题 1.1 复习巩固、综合运用与拓广探索 (L207-L260)",
                        "source_quote": "习题 1.1 复习巩固 1-2；综合运用 3-4；拓广探索 5. 集合论是德国数学家康托尔于 19 世纪末创立的...",
                        "transcription": "习题 1.1 全集：第1题元素与集合关系填空（含修复 OCR 错位：若 $B=\\{x \\mid x^2+x-6=0\\}$ 则 $3 \\notin B$；若 $C=\\{x \\in \\mathbf{N} \\mid 1 \\le x \\le 10\\}$ 则 $8 \\in C, 9.1 \\notin C$）；第2题列举法；第3题表示法互译（含由1,2,3组成无重复数字的自然数共15个）；第4题二次函数值域集与反比例函数定义域集；第5题康托尔集合论历史探究。",
                        "transcription_status": "verified",
                        "risk": "wording",
                        "reviewer": reviewer_name,
                        "reviewed_at": "2026-10-13 15:20:00"
                    }
                ]
            }

        elif aid == "reading_auditor":
            return {
                "diagnoses": [
                    {
                        "record_id": "diag_001",
                        "section_ref": "§1.1 集合的概念与确定性",
                        "checkpoint": "goal",
                        "passed": True,
                        "labels": ["goal_clarified", "criterion_explicit"],
                        "evidence": "试读者反馈：原书仅举例说明『较小的数』不能构成集合，自学时需补充可操作的判定法则（是否有客观、唯一、无歧义的检验标准）来应对『游泳能手』『接近0的数』等变式。",
                        "severity": "P2",
                        "fix_scope": "正文"
                    },
                    {
                        "record_id": "diag_002",
                        "section_ref": "§1.1 集合元素的互异性与相等",
                        "checkpoint": "error_location",
                        "passed": True,
                        "labels": ["implicit_constraint_exposed"],
                        "evidence": "试读者反馈：原书只用一句话提到『集合中的元素是不重复出现的』，但高一学生在解含参集合（如 a ∈ {1, a^2}）时极易漏掉互异性检验导致增根，正文中必须显式拆解互异性回代检验步骤。",
                        "severity": "P1",
                        "fix_scope": "正文"
                    },
                    {
                        "record_id": "diag_003",
                        "section_ref": "§1.1 常用数集及其记法",
                        "checkpoint": "prerequisite",
                        "passed": True,
                        "labels": ["symbol_disambiguation"],
                        "evidence": "试读者反馈：初学者极易混淆自然数集 N（含0）与正整数集 N* / N+（不含0），且原书练习2与习题1.1中存在多处 OCR 符号残缺（如 √2…Z、3, A、9.11___C），需在教材正文中给出清晰对照表并勘误原题符号。",
                        "severity": "P1",
                        "fix_scope": "正文"
                    },
                    {
                        "record_id": "diag_004",
                        "section_ref": "§1.1 列举法与代表元素辨析",
                        "checkpoint": "imitation",
                        "passed": True,
                        "labels": ["representation_trap"],
                        "evidence": "试读者反馈：在完成练习3(2)『一次函数 y=x+3 与 y=-2x+6 图象的交点组成的集合』时，试读者常误写为 {1, 4} 或 {x=1, y=4}，原因是不清楚点集的代表元素是有序数对 (x,y)，需专门设立点集与数集的对比示例。",
                        "severity": "P1",
                        "fix_scope": "正文"
                    },
                    {
                        "record_id": "diag_005",
                        "section_ref": "§1.1 描述法 {x ∈ A | P(x)} 的结构",
                        "checkpoint": "reasoning",
                        "passed": True,
                        "labels": ["structure_deconstructed"],
                        "evidence": "试读者反馈：在完成习题1.1第4题『二次函数 y=x^2-4 的函数值组成的集合』与『反比例函数 y=2/x 的自变量组成的集合』时，试读者分不清竖线左边写 x 还是 y，正文必须剖析竖线左侧『代表元素』与右侧『共同特征』的对应关系。",
                        "severity": "P1",
                        "fix_scope": "正文"
                    },
                    {
                        "record_id": "diag_006",
                        "section_ref": "§1.1 综合运用与康托尔集合论",
                        "checkpoint": "transfer",
                        "passed": True,
                        "labels": ["combinatorics_scaffolded"],
                        "evidence": "试读者反馈：习题1.1第3(2)题『由1,2,3抽出一部分或全部数字(没有重复)组成的一切自然数』，试读者直接列举容易漏数，需提供按位数（一位数、两位数、三位数）分类列举的思维支架。",
                        "severity": "P2",
                        "fix_scope": "下游互动系统"
                    }
                ]
            }

        elif aid == "structure_rebuilder":
            return {
                "nodes": [
                    {
                        "node_id": "node_pre_numbers_equations",
                        "kind": "prerequisite",
                        "statement": "初中数系与方程基础：自然数、整数、有理数、无理数、实数的分类，以及一元一次不等式、一元二次方程与二元一次方程组的求解。",
                        "source_refs": ["src_1_1_intro"],
                        "observable_evidence": "能独立求解 $x^2 - 3x + 2 = 0$、$x^2 = 2$ 及联立一次函数解析式求交点坐标。",
                        "first_use": "unit_01_set_concept",
                        "later_uses": ["unit_02_set_representation", "unit_03_comprehensive_application"],
                        "boundary_or_exception": "注意区分有理数范围与实数范围对方程是否有解的影响。"
                    },
                    {
                        "node_id": "node_elem_and_set",
                        "kind": "concept",
                        "statement": "元素与集合的定义：把研究对象统称为元素（用小写字母 $a,b,c,\\cdots$ 表示），把一些元素组成的总体叫做集合（用大写字母 $A,B,C,\\cdots$ 表示）。",
                        "source_refs": ["src_1_1_examples", "src_1_1_def_props"],
                        "observable_evidence": "能在具体数学或生活情境中准确指出哪个是个体元素、哪个是总体集合。",
                        "first_use": "unit_01_set_concept",
                        "later_uses": ["unit_02_set_representation", "unit_03_comprehensive_application"],
                        "boundary_or_exception": "集合是一个整体概念，元素是个体概念，二者层级不同。"
                    },
                    {
                        "node_id": "node_set_three_properties",
                        "kind": "concept",
                        "statement": "集合元素的三大特性与集合相等：确定性（元素在或不在集合中界限明确）、互异性（同一集合中元素互不相同、不重复）、无序性（元素排列无先后顺序）；构成元素完全相同的两集合相等。",
                        "source_refs": ["src_1_1_def_props"],
                        "observable_evidence": "能依据确定性判定一组对象能否构成集合，并能利用互异性检验含参集合中的参数取值。",
                        "first_use": "unit_01_set_concept",
                        "later_uses": ["unit_02_set_representation", "unit_03_comprehensive_application"],
                        "boundary_or_exception": "模棱两可的主观描述（如『较小的数』『游泳能手』）不满足确定性；含参问题求出参数后必须回代检验互异性。"
                    },
                    {
                        "node_id": "node_belong_relation",
                        "kind": "skill",
                        "statement": "元素与集合的属于关系：若 $a$ 是集合 $A$ 的元素，记作 $a \\in A$（读作 $a$ 属于 $A$）；若 $a$ 不是集合 $A$ 的元素，记作 $a \\notin A$（读作 $a$ 不属于 $A$）。",
                        "source_refs": ["src_1_1_def_props"],
                        "observable_evidence": "能判断具体对象与给定集合的从属关系，并正确书写 $\\in$ 或 $\\notin$。",
                        "first_use": "unit_01_set_concept",
                        "later_uses": ["unit_02_set_representation", "unit_03_comprehensive_application"],
                        "boundary_or_exception": "符号 $\\in$ 和 $\\notin$ 只能连接『元素』与『集合』，不能连接两个集合。"
                    },
                    {
                        "node_id": "node_standard_number_sets",
                        "kind": "concept",
                        "statement": "五大常用数集专用记法：自然数集（非负整数集）$\\mathbf{N}$、正整数集 $\\mathbf{N}^*$ 或 $\\mathbf{N}_+$、整数集 $\\mathbf{Z}$、有理数集 $\\mathbf{Q}$、实数集 $\\mathbf{R}$。",
                        "source_refs": ["src_1_1_num_sets", "src_1_1_practice", "src_1_1_exercises"],
                        "observable_evidence": "能准确判断 $0$、负整数、有限小数、分数、无理数（如 $\\sqrt{2}, \\pi$）分别属于或不属于哪个常用数集。",
                        "first_use": "unit_01_set_concept",
                        "later_uses": ["unit_02_set_representation", "unit_03_comprehensive_application"],
                        "boundary_or_exception": "核心边界：$0 \\in \\mathbf{N}$ 但 $0 \\notin \\mathbf{N}^*$；无限循环小数属于 $\\mathbf{Q}$，无限不循环小数（如 $\\sqrt{2}, \\pi$）属于 $\\mathbf{R}$ 但不属于 $\\mathbf{Q}$。"
                    },
                    {
                        "node_id": "node_roster_method",
                        "kind": "skill",
                        "statement": "列举法表示集合：把集合的所有元素一一列举出来，元素之间用逗号分隔，并用花括号 $\\{\\}$ 括起来表示集合的方法。",
                        "source_refs": ["src_1_1_roster", "src_1_1_exercises"],
                        "observable_evidence": "能将有限集或规律清晰的集合准确改写为列举法，做到不重不漏、格式规范。",
                        "first_use": "unit_02_set_representation",
                        "later_uses": ["unit_03_comprehensive_application"],
                        "boundary_or_exception": "花括号 $\\{\\}$ 本身已含『所有』『全体』之意，切忌在花括号内写『\\{所有实数\\}』或『\\{实数集\\}』；无限集（如 $x < 10$ 的实数解集）通常无法用列举法穷尽。"
                    },
                    {
                        "node_id": "node_set_builder_method",
                        "kind": "skill",
                        "statement": "描述法表示集合：设 $A$ 是一个集合，把集合 $A$ 中所有具有共同特征 $P(x)$ 的元素 $x$ 所组成的集合表示为 $\\{x \\in A \\mid P(x)\\}$（竖线也可写作冒号 $:$ 或分号 $;$，上下文明确时 $\\in \\mathbf{R}$ 可省略）。",
                        "source_refs": ["src_1_1_builder", "src_1_1_practice", "src_1_1_exercises"],
                        "observable_evidence": "能准确提取集合元素的代表元素符号、所属范围及共同特征 $P(x)$，写出规范的描述法表达式。",
                        "first_use": "unit_02_set_representation",
                        "later_uses": ["unit_03_comprehensive_application"],
                        "boundary_or_exception": "必须严格区分代表元素：数集 $\\{x \\mid y = x^2 - 4\\}$、函数值集 $\\{y \\mid y = x^2 - 4\\}$ 与点集 $\\{(x, y) \\mid y = x^2 - 4\\}$ 是三类完全不同的集合；注意 $\\in \\mathbf{Z}$ 或 $\\in \\mathbf{N}$ 不能随便省略。"
                    },
                    {
                        "node_id": "node_representation_conversion",
                        "kind": "skill",
                        "statement": "集合三种表示法（自然语言、列举法、描述法）的择优与互译：根据集合元素个数（有限或无限）与特征明显程度，灵活选择并相互转换表示方法。",
                        "source_refs": ["src_1_1_builder", "src_1_1_exercises"],
                        "observable_evidence": "能将描述法给出的有限整数集/方程根集转化为列举法，也能将列举法或自然语言集合转化为描述法。",
                        "first_use": "unit_02_set_representation",
                        "later_uses": ["unit_03_comprehensive_application"],
                        "boundary_or_exception": "将描述法转为列举法时，必须看清代表元素所属数集（如 $x \\in \\mathbf{N}$ 还是 $x \\in \\mathbf{Z}$）。"
                    },
                    {
                        "node_id": "node_parametric_set_analysis",
                        "kind": "skill",
                        "statement": "含参集合与组合分类建模：结合方程求解、元素互异性检验及按位数分类计数，解决含参集合求值与数字组合集合列举问题，并理解康托尔创立集合论的数学史意义。",
                        "source_refs": ["src_1_1_exercises"],
                        "observable_evidence": "能完整写出『列方程求参 -> 代回集合写出全部元素 -> 检验互异性排除增根』三步解答，并按分类法不重不漏列出组合自然数集。",
                        "first_use": "unit_03_comprehensive_application",
                        "later_uses": [],
                        "boundary_or_exception": "任何使集合中出现两个相同元素的参数值必须舍去。"
                    }
                ],
                "edges": [
                    {
                        "from_id": "node_pre_numbers_equations",
                        "to_id": "node_elem_and_set",
                        "relation": "动机铺垫"
                    },
                    {
                        "from_id": "node_elem_and_set",
                        "to_id": "node_set_three_properties",
                        "relation": "定义所需"
                    },
                    {
                        "from_id": "node_elem_and_set",
                        "to_id": "node_belong_relation",
                        "relation": "定义所需"
                    },
                    {
                        "from_id": "node_pre_numbers_equations",
                        "to_id": "node_standard_number_sets",
                        "relation": "前置依赖"
                    },
                    {
                        "from_id": "node_belong_relation",
                        "to_id": "node_standard_number_sets",
                        "relation": "定义所需"
                    },
                    {
                        "from_id": "node_set_three_properties",
                        "to_id": "node_roster_method",
                        "relation": "定义所需"
                    },
                    {
                        "from_id": "node_standard_number_sets",
                        "to_id": "node_set_builder_method",
                        "relation": "定义所需"
                    },
                    {
                        "from_id": "node_roster_method",
                        "to_id": "node_representation_conversion",
                        "relation": "并列对比"
                    },
                    {
                        "from_id": "node_set_builder_method",
                        "to_id": "node_representation_conversion",
                        "relation": "并列对比"
                    },
                    {
                        "from_id": "node_representation_conversion",
                        "to_id": "node_parametric_set_analysis",
                        "relation": "迁移应用"
                    }
                ]
            }

        elif aid == "unit_designer":
            return {
                "units": [
                    {
                        "unit_id": "unit_01_set_concept",
                        "title": "单元一：集合与元素的概念、三大特性及常用数集",
                        "objectives": [
                            "指出具体情境中的研究对象（元素）与总体（集合），并依据确定性判定一组对象能否构成集合",
                            "写出元素与集合之间的属于符号 $a \\in A$ 或不属于符号 $a \\notin A$，并准确判定具体数与五大常用数集（$\\mathbf{N}, \\mathbf{N}^*, \\mathbf{Z}, \\mathbf{Q}, \\mathbf{R}$）的关系"
                        ],
                        "completion_criteria": "独立完成教材思考题、练习1、练习2及习题1.1第1题，准确率100%，并能清晰说明 0 与无理数在各数集中的归属理由。",
                        "prerequisite_refs": ["node_pre_numbers_equations"],
                        "node_refs": [
                            "node_pre_numbers_equations",
                            "node_elem_and_set",
                            "node_set_three_properties",
                            "node_belong_relation",
                            "node_standard_number_sets"
                        ],
                        "section_refs": ["第一章引言", "§1.1 集合的概念"],
                        "status": "planned"
                    },
                    {
                        "unit_id": "unit_02_set_representation",
                        "title": "单元二：集合的表示方法——列举法与描述法",
                        "objectives": [
                            "构造有限集合的列举法表示，区分数集与点集的花括号书写规范",
                            "写出无限集合或具有共同特征集合的描述法 $\\{x \\in A \\mid P(x)\\}$，并实现自然语言、列举法与描述法三者之间的等价转换"
                        ],
                        "completion_criteria": "独立完成教材例1、例2、练习3及习题1.1第2、3、4题，准确区分二次函数值域集、反比例函数定义域集与函数图象交点点集的代表元素。",
                        "prerequisite_refs": ["node_set_three_properties", "node_standard_number_sets"],
                        "node_refs": [
                            "node_roster_method",
                            "node_set_builder_method",
                            "node_representation_conversion"
                        ],
                        "section_refs": ["§1.1 列举法", "§1.1 描述法"],
                        "status": "planned"
                    },
                    {
                        "unit_id": "unit_03_comprehensive_application",
                        "title": "单元三：集合概念综合运用、互异性检验与集合论历史探究",
                        "objectives": [
                            "求解含参集合中的参数值，并通过检验元素的互异性排除增根",
                            "分类列出无重复数字的自然数集合，并结合康托尔创立集合论的史实阐述集合语言作为现代数学基础的价值"
                        ],
                        "completion_criteria": "完成含参集合互异性综合诊断题、习题1.1全套综合解析与拓广探索第5题探究报告。",
                        "prerequisite_refs": ["node_set_three_properties", "node_representation_conversion"],
                        "node_refs": [
                            "node_parametric_set_analysis"
                        ],
                        "section_refs": ["§1.1 习题 1.1 综合运用", "§1.1 拓广探索"],
                        "status": "planned"
                    }
                ]
            }

        elif aid == "writer":
            good_text = """# 高中数学必修第一册自学讲义：1.1 集合的概念 (good.md)

> **教材版本**：人教A版高中数学必修第一册 · 第一章 集合与常用逻辑用语 · 1.1 集合的概念  
> **设计定位**：零跳跃、防卡壳、全覆盖自学教材（含教材原文全解、防坑指南、例题精析、练习与习题 1.1 全解及康托尔拓广探究）

---

## 单元一：集合与元素的概念、三大特性及常用数集

### 1. 【进入情境】
在初中数学中，我们遇到过两个非常有趣的现象：
- **现象一（代数范围决定方程是否有解）**：考察方程 $x^2 = 2$。如果我们只在**有理数范围**内寻找，找不到任何分数或有限小数的平方等于 $2$，此时方程**无解**；但当我们把视野扩展到**实数范围**内，方程就有了两个解 $x = \\sqrt{2}$ 和 $x = -\\sqrt{2}$。
- **现象二（空间维度决定几何图形形态）**：考察“所有到定点的距离等于定长的点”。如果限定在**同一平面内**，这些点组成一个**圆**；如果扩展到**三维空间中**，这些点则组成一个**球面**。

这两个现象告诉我们一个至关重要的数学原则：**明确研究对象、确定研究范围，是研究一切数学问题的基础。** 为了简洁、准确地表述数学研究对象及其研究范围，现代数学引入了最基础、最通用的语言工具——**集合（set）**。本章我们将系统学习集合的概念、基本关系和运算，并结合常用逻辑用语提升数学表达与推理的严密性。

### 2. 【明确目标】
完成本单元自学后，你将能够：
1. **指出**具体问题情境中的“元素”与“集合”，并依据**确定性**法则**判定**任意给定的总体能否构成集合。
2. **理解**并**运用**集合元素的三大特性（确定性、互异性、无序性）**判断**两个集合是否相等。
3. **写出**元素与集合之间的属于符号（$\\in$）或不属于符号（$\\notin$），并**判定**常见实数与五大常用数集（$\\mathbf{N}, \\mathbf{N}^*$ 或 $\\mathbf{N}_+, \\mathbf{Z}, \\mathbf{Q}, \\mathbf{R}$）的从属关系。

### 3. 【前置准备】
在开始本单元前，请快速回顾以下初中核心知识：
1. **实数的分类体系**：
   - **实数**分为**有理数**和**无理数**；
   - **有理数**包括**整数**（正整数、$0$、负整数）和**分数**（有限小数和无限循环小数都可以化为分数 $\\frac{q}{p}$，其中 $p, q$ 为整数且 $p \\neq 0$）；
   - **无理数**是无限不循环小数，例如 $\\sqrt{2}, -\\sqrt{3}, \\pi$ 等。
2. **一元二次方程求根**：例如解方程 $x^2 - 3x + 2 = 0$，利用因式分解法可得 $(x - 1)(x - 2) = 0$，故实数根为 $x_1 = 1, x_2 = 2$。

### 4. 【引导观察】
请仔细观察课本给出的 $6$ 个典型例子，思考它们研究的“个体对象”是什么，“总体”又是什么：
- **例 (1)**：$1 \\sim 10$ 之间的所有偶数；
  - *剖析*：个体对象是 $2, 4, 6, 8, 10$ 中的每一个偶数，这 $5$ 个偶数的总体构成一个集合。
- **例 (2)**：立德中学今年入学的全体高一学生；
  - *剖析*：个体对象是立德中学今年入学的每一位高一学生，全体高一学生构成一个集合。
- **例 (3)**：所有的正方形；
  - *剖析*：个体对象是每一个正方形（四条边相等且四个角都是直角的四边形），所有正方形的总体构成一个集合。
- **例 (4)**：到直线 $l$ 的距离等于定长 $d$ 的所有点；
  - *剖析*：个体对象是平面内满足“到直线 $l$ 距离等于 $d$”的每一个点（即平行于直线 $l$ 且距离为 $d$ 的两条平行直线上的每一个点），这些点的总体构成一个集合。
- **例 (5)**：方程 $x^2 - 3x + 2 = 0$ 的所有实数根；
  - *剖析*：解方程得 $x = 1$ 或 $x = 2$，个体对象是实数 $1$ 和 $2$，这两个根的总体构成一个集合。
- **例 (6)**：地球上的四大洋；
  - *剖析*：个体对象是太平洋、大西洋、印度洋、北冰洋，这四个大洋的总体构成一个集合。

> **【教材思考题精解】（课本第 2 页）**  
> **问题**：上面的例 (3) 到例 (6) 也都能组成集合吗？它们的元素分别是什么？  
> **解答**：例 (3) 到例 (6) **都能组成集合**！因为每个例子中对象的归属标准都是客观、明确、无歧义的：  
> - 例 (3) 的元素是：**每一个正方形**；  
> - 例 (4) 的元素是：**到直线 $l$ 的距离等于定长 $d$ 的每一个点**；  
> - 例 (5) 的元素是：**方程 $x^2 - 3x + 2 = 0$ 的实数根，即 $1$ 和 $2$**；  
> - 例 (6) 的元素是：**太平洋、大西洋、印度洋、北冰洋**。

### 5. 【概念命名与定义】

#### （1）元素与集合的定义
- **元素（element）**：一般地，我们把研究对象统称为**元素**。通常用小写拉丁字母 $a, b, c, \\cdots$ 表示集合中的元素。
- **集合（set）**：把一些元素组成的总体叫做**集合**（简称为**集**）。通常用大写拉丁字母 $A, B, C, \\cdots$ 表示集合。

#### （2）元素与集合的“属于”关系
给定一个集合 $A$ 和一个对象 $a$，它们之间只有以下两种关系之一：
- **属于（belong to）**：如果 $a$ 是集合 $A$ 的元素，就说 $a$ 属于集合 $A$，记作：
  $$a \\in A$$
- **不属于（not belong to）**：如果 $a$ 不是集合 $A$ 中的元素，就说 $a$ 不属于集合 $A$，记作：
  $$a \\notin A$$
- **示例**：若用 $A$ 表示例 (1) 中“$1 \\sim 10$ 之间的所有偶数”组成的集合，因为 $4$ 是 $1 \\sim 10$ 之间的偶数，而 $3$ 是奇数，所以有 $4 \\in A$，$3 \\notin A$。

#### （3）数学中五大常用数集及其专用记法
为了书写简洁，数学中对五类最常用的数集规定了专用的粗体大写字母记号（手写时常加双竖线如 $\\mathbb{N}, \\mathbb{Z}, \\mathbb{Q}, \\mathbb{R}$）：

| 数集名称 | 定义与所含元素范围 | 标准记号 | 关键易错边界辨析 |
| :--- | :--- | :---: | :--- |
| **非负整数集（自然数集）** | 全体非负整数组成的集合：$0, 1, 2, 3, \\cdots$ | $\\mathbf{N}$ | **特别注意：$0 \\in \\mathbf{N}$！**（现行国家标准规定 $0$ 是自然数） |
| **正整数集** | 全体正整数组成的集合：$1, 2, 3, \\cdots$ | $\\mathbf{N}^*$ 或 $\\mathbf{N}_+$ | 比自然数集 $\\mathbf{N}$ **少了元素 $0$**，即 $0 \\notin \\mathbf{N}^*$ |
| **整数集** | 全体整数组成的集合：$\\cdots, -2, -1, 0, 1, 2, \\cdots$ | $\\mathbf{Z}$ | 包含正整数、$0$ 和负整数；分数与小数（如 $0.5$）不属于 $\\mathbf{Z}$ |
| **有理数集** | 全体有理数（整数与分数）组成的集合 | $\\mathbf{Q}$ | 凡能写成 $\\frac{q}{p}$（$p, q \\in \\mathbf{Z}, p \\neq 0$）的数均属于 $\\mathbf{Q}$；无理数（如 $\\sqrt{2}, \\pi$）不属于 $\\mathbf{Q}$ |
| **实数集** | 全体实数（有理数与无理数）组成的集合 | $\\mathbf{R}$ | 初高中阶段未学复数前接触的所有有理数和无理数都属于 $\\mathbf{R}$ |

### 6. 【性质与理由】
为什么不是随便一堆东西都能叫“集合”？课本在定义集合后，立即给出了集合元素的**三大核心特性**及**集合相等**准则：

1. **确定性（Determinacy）**：
   - **含义**：给定的集合，它的元素必须是**确定的**。也就是说，给定一个集合 $A$ 和任何一个对象 $a$，那么“$a \\in A$”或“$a \\notin A$”必居其一，绝不能模棱两可。
   - **理由**：数学推理要求严密性。如果一个总体的边界是模糊的（例如“较小的数”、“高一学生中的游泳能手”），不同的人会有不同的判断标准，就无法确定某个对象是否属于它，后续的逻辑推理和集合运算也就无法进行。
2. **互异性（Distinctness）**：
   - **含义**：一个给定集合中的元素是**互不相同的**。也就是说，集合中的元素是不重复出现的。
   - **理由**：集合关注的是“有哪些研究对象 belong to 这个总体”，同一个对象在总体中只占据一个身份。例如方程 $(x-1)^2 = 0$ 有两个相等的实数根 $x_1 = x_2 = 1$，但它的解集只能包含一个元素 $1$，不能重复写两次。
3. **无序性（Unorderedness）**：
   - **含义**：集合中的元素没有先后顺序之分。
   - **理由**：**集合相等定义**——只要构成两个集合的元素是一样的，我们就称这两个集合是**相等的**（记作 $A = B$）。元素的排列次序不影响每个元素与集合的属于关系。

### 7. 【完整示例】
**【典型例题 1-1】**（对应课本练习 1 & 常用数集辨析）  
（1）判断下列元素的全体是否组成集合，并说明理由：  
① 与定点 $A, B$ 等距离的点；  
② 高中学生中的游泳能手。  
（2）用符号“$\\in$”或“$\\notin$”填空：  
$0$ ___ $\\mathbf{N}$；$-3$ ___ $\\mathbf{N}$；$0.5$ ___ $\\mathbf{Z}$；$\\sqrt{2}$ ___ $\\mathbf{Z}$；$\\frac{1}{3}$ ___ $\\mathbf{Q}$；$\\pi$ ___ $\\mathbf{R}$。

**【分步規範解答】**：  
**解（1）**：  
- 对于 ①：设平面（或空间）内任意一点为 $P$。判断点 $P$ 是否满足“与定点 $A, B$ 等距离”，只需检验线段长度关系 $PA = PB$ 是否成立（在平面内即线段 $AB$ 的垂直平分线上的点，在空间中即线段 $AB$ 的垂直平分面上的点）。这一检验标准客观、唯一、明确，满足元素的**确定性**，因此**能组成集合**。  
- 对于 ②：“游泳能手”没有明确、客观的量化标准（游多快算能手？会几种泳姿算能手？不明确），无法确定某位高中学生是否属于该总体，不满足元素的**确定性**，因此**不能组成集合**。

**解（2）**：  
- $0 \\in \\mathbf{N}$（理由：$\\mathbf{N}$ 是非负整数集，$0$ 是最小的非负整数）；  
- $-3 \\notin \\mathbf{N}$（理由：$-3$ 是负整数，不是非负整数）；  
- $0.5 \\notin \\mathbf{Z}$（理由：$0.5 = \\frac{1}{2}$ 是小数/分数，不是整数）；  
- $\\sqrt{2} \\notin \\mathbf{Z}$（理由：$\\sqrt{2} \\approx 1.414\\cdots$ 是无理数，不是整数）；  
- $\\frac{1}{3} \\in \\mathbf{Q}$（理由：$\\frac{1}{3}$ 是整数之比构成的分数，属于有理数集）；  
- $\\pi \\in \\mathbf{R}$（理由：圆周率 $\\pi$ 是无限不循环小数，即无理数，而实数集 $\\mathbf{R}$ 包含所有有理数和无理数）。

### 8. 【支架练习】
请独立完成本单元配套的阶梯诊断任务（详见任务库 `tasks.json` 中的三级提示与错因诊断）：
- **任务 `task_u1_01`**：判定给定对象总体能否构成集合，并剖析确定性边界。
- **任务 `task_u1_02`**：完成课本**习题 1.1 复习巩固第 1 题**全套填空（含国家集合、方程解集与常用数集的属于关系判断）。

### 9. 【边界与反例】
- **反例 1（违反确定性）**：“很接近 $0$ 的所有实数”、“班级里长得帅的男生”。反例剖析：“很接近”和“长得帅”都没有精确的数学度量边界，$0.001$ 算不算接近 $0$？无从判定，故不能构成集合。
- **反例 2（违反互异性）**：有人把单词 $\\text{book}$ 中的所有字母组成的集合包含的元素个数算作 $4$ 个（$b, o, o, k$）。反例剖析：字母 $o$ 重复出现了两次，根据集合元素的**互异性**，相同元素只保留一个，故该集合只有 $b, o, k$ 共 $3$ 个元素。
- **反例 3（混淆 $0$ 与数集关系）**：误写 $0 \\in \\mathbf{N}^*$ 或 $0 \\notin \\mathbf{N}$。边界警示：角标 $*$ 或 $+$ 代表剔除 $0$，务必牢记 $0 \\in \\mathbf{N}$ 且 $0 \\notin \\mathbf{N}^*$。

### 10. 【迁移任务】
如果在集合 $A$ 中含有两个元素 $1$ 和 $a^2$，且已知元素 $a \\in A$，你能猜想实数 $a$ 可能取哪些值吗？请尝试分类讨论 $a = 1$ 和 $a = a^2$ 两种情况，并思考：当 $a = 1$ 时，$a^2$ 的值是多少？这是否符合集合元素的**互异性**？（我们将在单元三对此类含参问题作深度专题突破）。

### 11. 【自检与桥接】
- **自检清单**：
  1. 我能否不看课本，默写出 $\\mathbf{N}, \\mathbf{N}^*$（或 $\\mathbf{N}_+$）$, \\mathbf{Z}, \\mathbf{Q}, \\mathbf{R}$ 五个记号各自代表的数集名称？
  2. 我能否清晰说出为什么“大于 $3$ 的全体实数”能构成集合，而“较大的实数”不能构成集合？
- **桥接下一单元**：在单元一中，我们都是用“自然语言”（文字叙述）来描述集合的。如果每次做数学题都要写一大段文字来描述集合，既繁琐又不便计算。除了自然语言之外，数学家还发明了哪两种简洁精准的符号表示法呢？让我们进入**单元二：列举法与描述法**。

---

## 单元二：集合的表示方法——列举法与描述法

### 1. 【进入情境】
在单元一中，我们用文字描述了“地球上的四大洋”和“方程 $x^2 - 3x + 2 = 0$ 的所有实数根”。如果我们要对这些集合进行后续运算，总不能一直抄写长串汉字。
- 对于元素个数较少、能够一个个点清的集合（如四大洋、方程的两个根 $1$ 和 $2$），我们能否像列购物清单一样，直接把元素全部摆出来？
- 而对于像“不等式 $x - 7 < 3$ 的解集（即 $x < 10$ 的全体实数）”这样包含**无穷多个元素**、根本无法一个个列完的集合，我们又该如何用一行简短的数学符号把它精确地刻画出来？

为了解决这两个问题，数学上分别引入了**列举法**和**描述法**。

### 2. 【明确目标】
完成本单元自学后，你将能够：
1. **构造**有限集合的**列举法**表示，严格遵守花括号 $\\{\\}$ 与逗号分隔规范，并**区分**数集与点集的列举格式。
2. **写出**集合的**描述法**标准式 $\\{x \\in A \\mid P(x)\\}$，准确**指出**其中的“代表元素”、“取值范围”与“共同特征”。
3. **比较**自然语言、列举法和描述法各自的特点，并在三种表示法之间熟练**转换**。

### 3. 【前置准备】
1. 熟练掌握单元一中的五大常用数集记号 $\\mathbf{N}, \\mathbf{N}^*, \\mathbf{Z}, \\mathbf{Q}, \\mathbf{R}$。
2. 掌握奇数与偶数的代数表达：任意整数 $k \\in \\mathbf{Z}$，偶数都可以表示为 $2k$，奇数都可以表示为 $2k + 1$（或 $2k - 1$）。
3. 掌握平面直角坐标系中两直线交点的求法：联立两个一次函数解析式组成二元一次方程组，所得的解 $(x, y)$ 即为交点坐标。

### 4. 【引导观察】
**观察一（从自然语言到列举法）**：
- “地球上的四大洋”组成的集合，直接把四个元素列在花括号内，表示为：
  $$\\{\\text{太平洋}, \\text{大西洋}, \\text{印度洋}, \\text{北冰洋}\\}$$
- “方程 $x^2 - 3x + 2 = 0$ 的所有实数根”组成的集合，直接把两个实数根列在花括号内，表示为：
  $$\\{1, 2\\}$$

**观察二（列举法的局限与描述法的诞生——课本第 93-105 行思考题）**：
> **【教材思考题精解】（课本第 3 页）**  
> **问题 (1)**：你能用自然语言描述集合 $\\{0, 3, 6, 9\\}$ 吗？  
> **解答 (1)**：观察 $0, 3, 6, 9$ 的共同特征——它们都是 $3$ 的倍数，且都是小于 $10$ 的自然数（非负整数）。因此可用自然语言描述为：**“小于 $10$ 且能被 $3$ 整除的所有自然数组成的集合”**（或“由 $0, 3, 6, 9$ 四个数组成的集合”）。  
> **问题 (2)**：你能用列举法表示不等式 $x - 7 < 3$ 的解集吗？  
> **解答 (2)**：**不能用列举法表示！** 因为解不等式 $x - 7 < 3$ 得 $x < 10$，满足 $x < 10$ 的实数有**无数个**，并且实数具有连续稠密性，无法把所有小于 $10$ 的实数一一列举出来。

既然无法一一列举，我们就抓住解集中所有元素的**共同特征**：① 它是实数（$x \\in \\mathbf{R}$）；② 它小于 $10$（$x < 10$）。把这两条写进花括号，中间用一条竖线“$\\mid$”隔开，就得到了：
$$\\{x \\in \\mathbf{R} \\mid x < 10\\}$$

### 5. 【概念命名与定义】

#### （1）列举法（Roster Method）
- **定义**：把集合的所有元素**一一列举**出来，元素与元素之间用逗号“$,$”隔开，并用花括号“$\\{\\}$”括起来表示集合的方法叫做**列举法**。
- **等价性说明**：由于集合中的元素具有**无序性**，元素完全相同的两个集合相等，与列举顺序无关。例如 $\\{1, 2\\}$ 与 $\\{2, 1\\}$ 表示同一个集合。

#### （2）描述法（Set-Builder Method）
- **定义**：一般地，设 $A$ 是一个集合，我们把集合 $A$ 中所有具有**共同特征 $P(x)$** 的元素 $x$ 所组成的集合表示为：
  $$\\{x \\in A \\mid P(x)\\}$$
  这种表示集合的方法称为**描述法**。有时也用冒号“$:$”或分号“$;$”代替竖线“$\\mid$”，写成 $\\{x \\in A : P(x)\\}$ 或 $\\{x \\in A ; P(x)\\}$。
- **结构拆解**：
  1. **花括号 $\\{\\}$**：表示这是一个集合（总体）；
  2. **竖线左侧 $x \\in A$**：$x$ 是集合的**代表元素**，$A$ 指明代表元素 $x$ 的**取值范围（研究范围）**；
  3. **竖线右侧 $P(x)$**：代表元素 $x$ 必须满足的**共同特征（限制条件）**。
- **省略约定**：如果从上下文的关系看，$x \\in \\mathbf{R}$ 或 $x \\in \\mathbf{Z}$ 是明确的，那么 $\\in \\mathbf{R}$、$\\in \\mathbf{Z}$ 可以省略，只写其元素 $x$。例如：
  - $D = \\{x \\in \\mathbf{R} \\mid x < 10\\}$ 可简写为 $D = \\{x \\mid x < 10\\}$；
  - $E = \\{x \\in \\mathbf{Z} \\mid x = 2k + 1, k \\in \\mathbf{Z}\\}$ 可简写为 $E = \\{x \\mid x = 2k + 1, k \\in \\mathbf{Z}\\}$。

### 6. 【性质与理由】

#### （1）为什么奇数集、偶数集和有理数集能用描述法精准刻画？
- **奇数集的推导**：对于每一个整数 $x \\in \\mathbf{Z}$，如果它能表示为 $x = 2k + 1$（$k \\in \\mathbf{Z}$）的形式，那么 $x$ 除以 $2$ 的余数为 $1$，它是一个奇数；反之，如果 $x$ 是一个奇数，那么 $x$ 除以 $2$ 的余数为 $1$，它必能表示为 $x = 2k + 1$（$k \\in \\mathbf{Z}$）的形式。因此，$x = 2k + 1$（$k \\in \\mathbf{Z}$）是所有奇数的充要共同特征，故**奇数集**表示为：
  $$\\{x \\in \\mathbf{Z} \\mid x = 2k + 1, k \\in \\mathbf{Z}\\}$$
- **偶数集的推导（课本第 115 行思考题解答）**：同理，整数 $x \\in \\mathbf{Z}$ 能被 $2$ 整除当且仅当它能表示为 $x = 2k$（$k \\in \\mathbf{Z}$）的形式。因此，**偶数集**表示为：
  $$\\{x \\in \\mathbf{Z} \\mid x = 2k, k \\in \\mathbf{Z}\\}$$
- **有理数集的推导**：实数集 $\\mathbf{R}$ 中，整数、有限小数和无限循环小数都具有分数 $\\frac{q}{p}$（$p, q \\in \\mathbf{Z}, p \\neq 0$）的形式，因此**有理数集 $\\mathbf{Q}$** 用描述法表示为：
  $$\\mathbf{Q} = \\left\\{x \\in \\mathbf{R} \\;\\middle|\\; x = \\frac{q}{p}, p, q \\in \\mathbf{Z}, p \\neq 0\\right\\}$$
- **描述法的基本性质**：根据描述法的定义可以直接验证，对于任何元素 $y \\in \\{x \\in A \\mid P(x)\\}$，必有 $y \\in A$ 且性质 $P(y)$ 成立；反之，若 $y \\in A$ 且 $P(y)$ 成立，则必有 $y \\in \\{x \\in A \\mid P(x)\\}$。

#### （2）三种集合表示方法的特点对比（课本第 185 行思考题解答）
| 表示方法 | 核心优点 | 适用场景 | 局限或注意事项 |
| :--- | :--- | :--- | :--- |
| **自然语言** | 通俗易懂，贴近日常直觉 | 概念初引入或文字背景描述（如“地球上的四大洋”） | 不够简练，不便于直接进行数学符号运算 |
| **列举法** | 直观明了，集合中的每一个元素一目了然 | 元素个数较少，或元素虽多但有限且具体元素至关重要（如 $\\{0, 1\\}$） | 无法表示元素无限且无简单规律的实数区间集合 |
| **描述法** | 抽象概括力强，既能表示有限集也能表示无限集 | 元素个数无限（如不等式解集），或需要凸显元素的共同代数特征 | 必须看清竖线左侧的“代表元素”究竟是数还是点 |

### 7. 【完整示例】

#### 【教材例 1 精析】（课本第 3 页）
**题目**：用列举法表示下列集合：  
（1）小于 $10$ 的所有自然数组成的集合；  
（2）方程 $x^2 = x$ 的所有实数根组成的集合。  
**规范解答**：  
（1）设小于 $10$ 的所有自然数组成的集合为 $A$。因为自然数集 $\\mathbf{N}$ 包含 $0$，小于 $10$ 的自然数依次为 $0, 1, 2, 3, 4, 5, 6, 7, 8, 9$，所以用列举法表示为：
$$A = \\{0, 1, 2, 3, 4, 5, 6, 7, 8, 9\\}$$
（注：由于元素无序性，写成 $A = \\{9, 8, 7, 6, 5, 4, 3, 2, 1, 0\\}$ 等也完全正确。）  
（2）设方程 $x^2 = x$ 的所有实数根组成的集合为 $B$。移项因式分解得 $x(x - 1) = 0$，解得两个实数根 $x_1 = 0, x_2 = 1$，所以用列举法表示为：
$$B = \\{0, 1\\}$$

#### 【教材例 2 精析】（课本第 4 页）
**题目**：试分别用描述法和列举法表示下列集合：  
（1）方程 $x^2 - 2 = 0$ 的所有实数根组成的集合 $A$；  
（2）由大于 $10$ 且小于 $20$ 的所有整数组成的集合 $B$。  
**规范解答**：  
（1）设 $x \\in A$，则 $x$ 是一个实数，且满足方程 $x^2 - 2 = 0$。  
- 用**描述法**表示为：
  $$A = \\{x \\in \\mathbf{R} \\mid x^2 - 2 = 0\\}$$
- 解方程 $x^2 - 2 = 0$ 得两个实数根 $\\sqrt{2}, -\\sqrt{2}$，故用**列举法**表示为：
  $$A = \\{\\sqrt{2}, -\\sqrt{2}\\}$$
（2）设 $x \\in B$，则 $x$ 是一个整数，即 $x \\in \\mathbf{Z}$，且满足不等式 $10 < x < 20$。  
- 用**描述法**表示为：
  $$B = \\{x \\in \\mathbf{Z} \\mid 10 < x < 20\\}$$
- 大于 $10$ 且小于 $20$ 的整数共有 $9$ 个，依次为 $11, 12, 13, 14, 15, 16, 17, 18, 19$，故用**列举法**表示为：
  $$B = \\{11, 12, 13, 14, 15, 16, 17, 18, 19\\}$$

#### 【教材练习 3 精析】（课本第 5 页——重点突破“交点点集”）
**题目**：用适当的方法表示下列集合：  
（1）由方程 $x^2 - 9 = 0$ 的所有实数根组成的集合；  
（2）一次函数 $y = x + 3$ 与 $y = -2x + 6$ 图象的交点组成的集合；  
（3）不等式 $4x - 5 < 3$ 的解集。  
**规范解答**：  
（1）解方程 $x^2 - 9 = 0$ 得 $x = 3$ 或 $x = -3$，元素有限且只有 $2$ 个，适合用**列举法**表示为 $\\{-3, 3\\}$（或用描述法表示为 $\\{x \\in \\mathbf{R} \\mid x^2 - 9 = 0\\}$）。  
（2）**【高危易错点】** 本题研究对象是“**图象的交点**”，平面直角坐标系中的**点**必须用**有序实数对 $(x, y)$** 表示！  
联立方程组 $\\begin{cases} y = x + 3 \\\\ y = -2x + 6 \\end{cases}$，将 $y = x + 3$ 代入第二式得 $x + 3 = -2x + 6$，即 $3x = 3$，解得 $x = 1$，代入得 $y = 4$。故两直线交点坐标为 $(1, 4)$。  
- 用**列举法**表示为：$\\{(1, 4)\\}$；  
- 用**描述法**表示为：$\\{(x, y) \\mid y = x + 3 \\text{ 且 } y = -2x + 6\\}$。  
（切忌写成 $\\{1, 4\\}$，因为 $\\{1, 4\\}$ 表示含有两个实数 $1$ 和 $4$ 的数集，而不是一个点的集合！）  
（3）解不等式 $4x - 5 < 3$，移项得 $4x < 8$，即 $x < 2$。解集包含无数个实数，必须用**描述法**表示为：
$$\\{x \\in \\mathbf{R} \\mid x < 2\\} \\quad (\\text{或简写为 } \\{x \\mid x < 2\\})$$

### 8. 【支架练习】
请完成任务库中的以下两项核心训练：
- **任务 `task_u2_01`**：完成课本**习题 1.1 复习巩固第 2 题**（用列举法表示整数区间集合、二次方程根集与不等式整数解集）及交点点集辨析。
- **任务 `task_u2_02`**：完成课本**习题 1.1 综合运用第 3 题与第 4 题**（集合表示法互译，特别是区分二次函数 $y = x^2 - 4$ 的函数值集合与反比例函数 $y = \\frac{2}{x}$ 的自变量集合）。

### 9. 【边界与反例】
**四大经典易错反例剖析**：
1. **符号语义重复反例**：把实数集写成 $\\{\\text{全体实数}\\}$ 或 $\\{\\mathbf{R}\\}$。
   - *诊断*：花括号 $\\{\\}$ 本身就代表“全体、所有……组成的集合”，因此 $\\{\\text{实数}\\}$ 才是实数集 $\\mathbf{R}$，而 $\\{\\mathbf{R}\\}$ 表示“以实数集 $\\mathbf{R}$ 这一个集合作为唯一元素的集合”，二者截然不同！
2. **数集与点集混淆反例**：把一次函数交点集写成 $\\{1, 4\\}$ 或 $\\{x = 1, y = 4\\}$。
   - *诊断*：$\\{1, 4\\}$ 含有 $2$ 个实数元素；$\\{(1, 4)\\}$ 只含有 $1$ 个点元素（即坐标为 $(1, 4)$ 的点）。
3. **描述法代表元素张冠李戴反例**：针对函数 $y = x^2 - 4$，请对比以下四个集合的本质差异：
   - $A = \\{x \\mid y = x^2 - 4\\}$：代表元素是自变量 $x$，对 $x$ 无限制，故 $A = \\mathbf{R}$（自变量取值集合/定义域）；
   - $B = \\{y \\mid y = x^2 - 4\\}$：代表元素是函数值 $y$，因 $x^2 \\ge 0$，故 $y = x^2 - 4 \\ge -4$，即 $B = \\{y \\mid y \\ge -4\\}$（函数值集合/值域）；
   - $C = \\{(x, y) \\mid y = x^2 - 4\\}$：代表元素是点 $(x, y)$，表示抛物线 $y = x^2 - 4$ 上的**所有点组成的点集**；
   - $D = \\{y = x^2 - 4\\}$：没有竖线和代表元素，表示以“方程 $y = x^2 - 4$”这一个式子为元素的单元素集，**绝不能用来表示数集或点集**！
4. **忽略代表元素数集限制反例**：把 $B = \\{x \\in \\mathbf{Z} \\mid -3 < 2x - 1 < 3\\}$ 写成 $\\{x \\mid -1 < x < 2\\}$。
   - *诊断*：原集合限定了 $x \\in \\mathbf{Z}$，解不等式得 $-1 < x < 2$ 后，其中的整数只有 $0$ 和 $1$，故该集合实际上是有限集 $\\{0, 1\\}$，忽略 $x \\in \\mathbf{Z}$ 会把有限整数集错当成无限实数区间！

### 10. 【迁移任务】
尝试把集合 $M = \\left\\{x \\in \\mathbf{N} \\;\\middle|\\; \\frac{6}{3 - x} \\in \\mathbf{N}^*\\right\\}$ 用**列举法**表示出来。
- *思考支架*：这里要求代表元素 $x$ 本身是自然数（$x \\in \\mathbf{N}$），同时分式 $\\frac{6}{3 - x}$ 的值是正整数（$\\in \\mathbf{N}^*$），说明 $3 - x$ 必须是 $6$ 的正因数（即 $1, 2, 3, 6$）。请你逐个解出 $x$，并检验 $x \\in \\mathbf{N}$ 是否成立！

### 11. 【自检与桥接】
- **自检清单**：
  1. 看到描述法 $\\{\\text{甲} \\mid \\text{乙}\\}$ 时，我是否养成了“先看竖线左边甲是谁（是数 $x$、函数值 $y$ 还是点 $(x,y)$，属于哪个大数集），再看竖线右边乙是什么限制条件”的习惯？
  2. 我能否独立把有限描述法集合准确无误地改写为列举法？
- **桥接下一单元**：掌握了集合的概念与表示法后，如何综合运用这些知识解决课本《习题 1.1》中的全部题目、攻克高一常考的“含参集合互异性陷阱”，并领略康托尔创立集合论的伟大思想？让我们进入**单元三：集合概念综合运用、互异性检验与集合论历史探究**。

---

## 单元三：集合概念综合运用、互异性检验与集合论历史探究

### 1. 【进入情境】
在完成了基础概念与表示法的学习后，同学们在实战解题中往往会遇到三类挑战：
1. **多条件组合列举问题**：如课本习题 1.1 第 3(2) 题“由 $1, 2, 3$ 这三个数字抽出一部分或全部数字（没有重复）所组成的一切自然数”，怎样做到不重不漏？
2. **含参集合中的隐形陷阱**：当集合元素中含有字母参数（如 $A = \\{1, a, a^2 - a\\}$）时，求出的参数值为什么常常因为违反“互异性”而成为增根？
3. **数学文化与思想溯源**：为什么希尔伯特盛赞康托尔的集合论是“数学思想的惊人的产物，在纯粹理性的范畴中人类活动的最美的表现之一”？

本单元将带你彻底打通这三大高阶关卡，并给出课本《习题 1.1》的全套标准解答。

### 2. 【明确目标】
完成本单元自学后，你将能够：
1. **求解**含有字母参数的集合属于或相等问题，并强制执行“**代回检验互异性**”步骤以**诊断**并剔除增根。
2. **分类列出**满足组合限制条件的有限集合，**完成**课本《习题 1.1》复习巩固与综合运用的全部题目。
3. **构建**关于康托尔创立集合论的简短读书探究报告，**验证**集合语言对刻画“无限”与奠定现代数学大厦的核心价值。

### 3. 【前置准备】
1. 集合元素的三大特性（确定性、**互异性**、无序性）。
2. 列举法与描述法的规范格式及转换规则。
3. 分类加法计数思想：按元素的位数（一位数、两位数、三位数）分步有序枚举。

### 4. 【引导观察】
让我们先观察一个高一月考中最经典的“错题现场”：
> **问题**：已知集合 $A = \\{2, 4, a^2 - 2a + 2\\}$，若 $2 \\in A$ 且 $a \\in A$，求实数 $a$ 的值。  
> **某同学的错误解法**：因为 $a \\in A$，所以 $a = 2$ 或 $a = 4$ 或 $a = a^2 - 2a + 2$。解 $a = a^2 - 2a + 2$ 得 $a^2 - 3a + 2 = 0$，即 $a = 1$ 或 $a = 2$。综上，$a = 1, 2, 4$。  
> **为什么错了？**  
> 我们把 $a = 2$ 代回集合 $A$ 中算一算：此时 $a^2 - 2a + 2 = 2^2 - 2 \\times 2 + 2 = 2$！于是集合 $A$ 变成了 $\\{2, 4, 2\\}$，出现了两个重复的元素 $2$，直接违背了集合元素的**互异性**！

从这个观察中，我们提炼出一条铁律：**凡是求解含参集合问题，求出参数值后，必须将参数代回原集合写出全部元素的具体数值，检验任意两个元素是否互不相同！**

### 5. 【概念命名与定义】

#### （1）含参集合的“互异性三步检验法”
设含参集合为 $A = \\{f_1(a), f_2(a), \\cdots, f_n(a)\\}$，已知某元素 $m \\in A$（或两集合相等），标准求解流程定义为：
- **第一步（分类列方程）**：根据属于关系 $m \\in A$，分情况令 $f_1(a) = m, f_2(a) = m, \\cdots, f_n(a) = m$，解出参数 $a$ 的所有候选值；
- **第二步（代回还原集合）**：将每一个候选值 $a$ 分别代入 $f_1(a), f_2(a), \\cdots, f_n(a)$，计算出集合中每个位置的数值；
- **第三步（互异性裁决）**：检查集合中是否存在相等的元素（即是否存在 $i \\neq j$ 使得 $f_i(a) = f_j(a)$）。若存在重复元素，则该候选值违反互异性，**必须舍去**；若所有元素互不相同，则保留该解。

#### （2）有限组合集合的“字典序分类列举法”
当集合元素是由若干数字按规则组成的数时，为了保证**不重不漏**，必须先按**位数**（一位数、两位数、三位数……）分类，再在每一类中按从小到大的**字典序**（首位从最小数字排起）依次列举。

### 6. 【性质与理由】
为什么集合论的创立具有划时代的意义？（对应课本第 253-260 行【拓广探索】）
1. **越过“有限数集”的限制，首次用严格数学语言驯服“无限”**：
   在 19 世纪末德国数学家**康托尔（Georg Cantor, 1845—1918）**创立集合论之前，数学家大多只敢讨论有限的数或潜无限过程。康托尔在研究三角级数唯一性问题时，勇敢地越过了“数集”的限制，提出了一般性的“集合”概念（无论是数、点、函数还是任意抽象对象，只要满足确定性与互异性均可构成集合），并利用集合之间的“一一对应”建立了无穷集合的势（基数）理论，证明了有理数集 $\\mathbf{Q}$ 与自然数集 $\\mathbf{N}$ 一样多（可数无穷），而实数集 $\\mathbf{R}$ 的无穷层级更高（不可数无穷）。
2. **统一现代数学的公理化基石**：
   有了集合语言，函数被严格定义为两个集合之间的对应关系，几何图形被定义为满足特定条件的点集，概率论建立在样本空间（基本事件集合）之上。正如希尔伯特所赞誉的，它是“数学思想的惊人的产物”；罗素也评价其为“可能是这个时代所能夸耀的最伟大的工作”。

### 7. 【完整示例】
本节给出**课本《习题 1.1》（第 207–260 行）全套逐题精析**：

#### 一、复习巩固（课本第 209–230 行）
**【第 1 题】** 用符号“$\\in$”或“$\\notin$”填空：  
（1）设 $A$ 为所有亚洲国家组成的集合，则：中国 ___ $A$，美国 ___ $A$，印度 ___ $A$，英国 ___ $A$；  
（2）若 $A = \\{x \\mid x^2 = x\\}$，则 $-1$ ___ $A$；  
（3）若 $B = \\{x \\mid x^2 + x - 6 = 0\\}$，则 $3$ ___ $B$；  
（4）若 $C = \\{x \\in \\mathbf{N} \\mid 1 \\le x \\le 10\\}$，则 $8$ ___ $C$，$9.1$ ___ $C$。

**【完整解析】**：  
- **（1）** 中国和印度位于亚洲，美国位于北美洲，英国位于欧洲。故填：**中国 $\\in A$，美国 $\\notin A$，印度 $\\in A$，英国 $\\notin A$**。  
- **（2）** 检验 $x = -1$ 是否满足特征性质 $x^2 = x$：左边 $(-1)^2 = 1$，右边 $= -1$，左边 $\\neq$ 右边（或解方程得 $A = \\{0, 1\\}$）。故填：**$-1 \\notin A$**。  
- **（3）** 检验 $x = 3$ 是否满足方程 $x^2 + x - 6 = 0$：代入得 $3^2 + 3 - 6 = 6 \\neq 0$（或因式分解 $(x+3)(x-2)=0$ 解得 $B = \\{-3, 2\\}$）。故填：**$3 \\notin B$**。  
- **（4）** 集合 $C$ 的元素需同时满足“$x \\in \\mathbf{N}$（自然数）”和“$1 \\le x \\le 10$”。$8$ 是 $1$ 到 $10$ 之间的自然数，而 $9.1$ 是小数（不是自然数）。故填：**$8 \\in C$，$9.1 \\notin C$**。

**【第 2 题】** 用列举法表示下列集合：  
（1）大于 $1$ 且小于 $6$ 的整数；  
（2）$A = \\{x \\mid (x - 1)(x + 2) = 0\\}$；  
（3）$B = \\{x \\in \\mathbf{Z} \\mid -3 < 2x - 1 < 3\\}$。

**【完整解析】**：  
- **（1）** 满足 $1 < x < 6$ 的整数有 $2, 3, 4, 5$，用列举法表示为：
  $$\\{2, 3, 4, 5\\}$$
- **（2）** 解方程 $(x - 1)(x + 2) = 0$，得实数根 $x_1 = 1, x_2 = -2$，用列举法表示为：
  $$A = \\{1, -2\\} \\quad (\\text{或 } \\{-2, 1\\})$$
- **（3）** 先解不等式 $-3 < 2x - 1 < 3$：不等式三边同加 $1$ 得 $-2 < 2x < 4$，三边同除以 $2$ 得 $-1 < x < 2$。再结合代表元素限制 $x \\in \\mathbf{Z}$，满足 $-1 < x < 2$ 的整数只有 $0$ 和 $1$，故用列举法表示为：
  $$B = \\{0, 1\\}$$

#### 二、综合运用（课本第 231–250 行）
**【第 3 题】** 把下列集合用另一种方法表示出来：  
（1）$\\{2, 4, 6, 8, 10\\}$；  
（2）由 $1, 2, 3$ 这三个数字抽出一部分或全部数字（没有重复）所组成的一切自然数；  
（3）$\\{x \\in \\mathbf{N} \\mid 3 < x < 7\\}$；  
（4）中国古代四大发明。

**【完整解析】**：  
- **（1）** 原集合为列举法，观察知其元素是大于 $1$ 且小于 $11$ 的偶数（或正偶数中前 $5$ 个），改用**描述法**表示为：
  $$\\{x \\in \\mathbf{Z} \\mid x = 2k, 1 \\le k \\le 5, k \\in \\mathbf{Z}\\} \\quad (\\text{或用自然语言：由 } 1 \\sim 10 \\text{ 之间的所有偶数组成的集合})$$
- **（2）** 原集合为自然语言，元素个数有限，改用**列举法**。按自然数的位数分类枚举：  
  - **一位数**（抽 $1$ 个数字，共 $3$ 个）：$1, 2, 3$；  
  - **两位数**（抽 $2$ 个不同数字排列，共 $3 \\times 2 = 6$ 个）：$12, 13, 21, 23, 31, 32$；  
  - **三位数**（抽全部 $3$ 个数字排列，共 $3 \\times 2 \\times 1 = 6$ 个）：$123, 132, 213, 231, 312, 321$。  
  汇总共 $3 + 6 + 6 = 15$ 个自然数，用列举法表示为：
  $$\\{1, 2, 3, 12, 13, 21, 23, 31, 32, 123, 132, 213, 231, 312, 321\\}$$
- **（3）** 原集合为描述法，满足 $3 < x < 7$ 的自然数有 $4, 5, 6$，改用**列举法**表示为：
  $$\\{4, 5, 6\\}$$
- **（4）** 原集合为自然语言，中国古代四大发明是造纸术、印刷术、火药、指南针，改用**列举法**表示为：
  $$\\{\\text{造纸术}, \\text{印刷术}, \\text{火药}, \\text{指南针}\\}$$

**【第 4 题】** 用适当的方法表示下列集合：  
（1）二次函数 $y = x^2 - 4$ 的函数值组成的集合；  
（2）反比例函数 $y = \\frac{2}{x}$ 的自变量组成的集合；  
（3）不等式 $3x \\ge 4 - 2x$ 的解集。

**【完整解析】**：  
- **（1）** 研究对象是“**函数值 $y$**”，故代表元素为 $y$。用**描述法**可直接表示为：
  $$\\{y \\mid y = x^2 - 4\\} \\quad \\left(\\text{因 } x \\in \\mathbf{R} \\text{ 时 } x^2 \\ge 0, \\text{ 故 } y \\ge -4, \\text{ 化简后也可写为 } \\{y \\mid y \\ge -4\\}\\right)$$
- **（2）** 研究对象是“**自变量 $x$**”，故代表元素为 $x$。反比例函数分母不能为 $0$，即 $x \\neq 0$，用**描述法**表示为：
  $$\\left\\{x \\;\\middle|\\; y = \\frac{2}{x}\\right\\} \\quad \\left(\\text{即 } \\{x \\in \\mathbf{R} \\mid x \\neq 0\\}\\right)$$
- **（3）** 解不等式 $3x \\ge 4 - 2x$：移项得 $3x + 2x \\ge 4$，即 $5x \\ge 4$，解得 $x \\ge \\frac{4}{5}$。用**描述法**表示为：
  $$\\left\\{x \\;\\middle|\\; x \\ge \\frac{4}{5}\\right\\}$$

#### 三、拓广探索（课本第 257–260 行）
**【第 5 题】** 结合康托尔创立集合论的史实，撰写简短报告阐述对希尔伯特与罗素评价的认识。  
**【探究报告示范】**：  
1. **研究对象的全面抽象化**：康托尔越过了传统数学只研究“数集”的局限，将点、曲线、函数乃至任意确定对象都纳入“集合”范畴，使数学拥有了统一的底层词汇。  
2. **首次赋予“实无限”严格数学地位**：通过集合间的一一对应（双射），康托尔揭示了无穷集合的部分可以与整体等势（如偶数集与整数集等势），并证明了实数集 $\\mathbf{R}$ 的基数严格大于自然数集 $\\mathbf{N}$ 的基数，开辟了超穷数理论——这正是希尔伯特称之为“纯粹理性范畴中人类活动最美表现”的原因。  
3. **现代数学公理化的逻辑起点**：罗素提出的悖论（如理发师悖论 $R = \\{x \\mid x \\notin x\\}$）进一步推动了策梅洛-弗兰克尔公理化集合论（ZFC）的建立，严密规定了描述法必须从已有集合 $A$ 中筛选元素 $\\{x \\in A \\mid P(x)\\}$（这正是课本第 119 行强调“设 $A$ 是一个集合，把集合 $A$ 中所有具有共同特征 $P(x)$ 的元素表示为 $\\{x \\in A \\mid P(x)\\}$”的深层数学根源！）。

### 8. 【支架练习】
请完成任务 `task_u3_01`：综合运用集合元素的互异性求解含参集合问题，并完成组合自然数集与集合论公理化限制条件辨析。

### 9. 【边界与反例】
- **高阶反例（含参集合漏检互异性）**：已知集合 $A = \\{a + 2, (a + 1)^2, a^2 + 3a + 3\\}$，若 $1 \\in A$，求实数 $a$ 的值。
  - **情况 1**：若 $a + 2 = 1$，则 $a = -1$。代回得 $(a+1)^2 = 0$，$a^2 + 3a + 3 = 1 - 3 + 3 = 1$。此时集合中第 1 项与第 3 项均为 $1$（出现重复元素 $\\{1, 0, 1\\}$），违反互异性，故 **$a = -1$ 舍去**！
  - **情况 2**：若 $(a + 1)^2 = 1$，则 $a + 1 = 1$ 或 $a + 1 = -1$，解得 $a = 0$ 或 $a = -2$。
    - 当 $a = 0$ 时，代回得 $a + 2 = 2$，$(a+1)^2 = 1$，$a^2 + 3a + 3 = 3$，此时 $A = \\{2, 1, 3\\}$，三元素互不相同，**$a = 0$ 符合题意**！
    - 当 $a = -2$ 时，代回得 $a + 2 = 0$，$(a+1)^2 = 1$，$a^2 + 3a + 3 = 4 - 6 + 3 = 1$，此时第 2 项与第 3 项均为 $1$（出现重复元素 $\\{0, 1, 1\\}$），违反互异性，故 **$a = -2$ 舍去**！
  - **情况 3**：若 $a^2 + 3a + 3 = 1$，即 $a^2 + 3a + 2 = 0$，解得 $a = -1$ 或 $a = -2$，由上述检验知均违反互异性，全部舍去。
  - **最终结论**：实数 $a$ 的唯一取值为 $a = 0$。

### 10. 【迁移任务】
已知两个集合 $P = \\{x \\mid x = 2k, k \\in \\mathbf{Z}\\}$（偶数集）与 $Q = \\{x \\mid x = 2k + 1, k \\in \\mathbf{Z}\\}$（奇数集）。如果从集合 $P$ 中任取一个元素 $a \\in P$，从集合 $Q$ 中任取一个元素 $b \\in Q$：
1. 试判断 $a + b$ 属于集合 $P$ 还是集合 $Q$，并写出代数推导过程；
2. 试判断 $a \\cdot b$ 属于集合 $P$ 还是集合 $Q$，并写出代数推导过程。

### 11. 【自检与桥接】
- **全节终极自检清单**：
  1. 我能否准确区分元素与集合的符号（$\\in, \\notin$），并熟记五大数集 $\\mathbf{N}, \\mathbf{N}^*, \\mathbf{Z}, \\mathbf{Q}, \\mathbf{R}$ 的边界（特别是 $0$ 的归属）？
  2. 我能否熟练运用列举法和描述法表示数集与点集，并做到看清竖线左侧的代表元素？
  3. 遇到含参集合问题时，我是否形成了“求参必代回检验互异性”的条件反射？
- **桥接下一节（1.2 集合间的基本关系）**：在本节（1.1）中，我们研究了**元素与集合之间**的“属于（$\\in$）”关系。那么，**两个集合与集合之间**（例如自然数集 $\\mathbf{N}$ 与整数集 $\\mathbf{Z}$ 之间，或者 $\\{1, 2\\}$ 与 $\\{1, 2, 3\\}$ 之间）又存在着怎样的包含关系呢？这就是下一节《1.2 集合间的基本关系（子集、真子集与空集）》将要探索的核心主题！
"""
            return {
                "good_md": good_text,
                "units": [
                    {
                        "unit_id": "unit_01_set_concept",
                        "title": "单元一：集合与元素的概念、三大特性及常用数集",
                        "objectives": [
                            "指出具体情境中的研究对象（元素）与总体（集合），并依据确定性判定一组对象能否构成集合",
                            "写出元素与集合之间的属于符号 $a \\in A$ 或不属于符号 $a \\notin A$，并准确判定具体数与五大常用数集（$\\mathbf{N}, \\mathbf{N}^*, \\mathbf{Z}, \\mathbf{Q}, \\mathbf{R}$）的关系"
                        ],
                        "completion_criteria": "独立完成教材思考题、练习1、练习2及习题1.1第1题，准确率100%，并能清晰说明 0 与无理数在各数集中的归属理由。",
                        "prerequisite_refs": ["node_pre_numbers_equations"],
                        "node_refs": [
                            "node_pre_numbers_equations",
                            "node_elem_and_set",
                            "node_set_three_properties",
                            "node_belong_relation",
                            "node_standard_number_sets"
                        ],
                        "section_refs": ["第一章引言", "§1.1 集合的概念"],
                        "status": "drafted"
                    },
                    {
                        "unit_id": "unit_02_set_representation",
                        "title": "单元二：集合的表示方法——列举法与描述法",
                        "objectives": [
                            "构造有限集合的列举法表示，区分数集与点集的花括号书写规范",
                            "写出无限集合或具有共同特征集合的描述法 $\\{x \\in A \\mid P(x)\\}$，并实现自然语言、列举法与描述法三者之间的等价转换"
                        ],
                        "completion_criteria": "独立完成教材例1、例2、练习3及习题1.1第2、3、4题，准确区分二次函数值域集、反比例函数定义域集与函数图象交点点集的代表元素。",
                        "prerequisite_refs": ["node_set_three_properties", "node_standard_number_sets"],
                        "node_refs": [
                            "node_roster_method",
                            "node_set_builder_method",
                            "node_representation_conversion"
                        ],
                        "section_refs": ["§1.1 列举法", "§1.1 描述法"],
                        "status": "drafted"
                    },
                    {
                        "unit_id": "unit_03_comprehensive_application",
                        "title": "单元三：集合概念综合运用、互异性检验与集合论历史探究",
                        "objectives": [
                            "求解含参集合中的参数值，并通过检验元素的互异性排除增根",
                            "分类列出无重复数字的自然数集合，并结合康托尔创立集合论的史实阐述集合语言作为现代数学基础的价值"
                        ],
                        "completion_criteria": "完成含参集合互异性综合诊断题、习题1.1全套综合解析与拓广探索第5题探究报告。",
                        "prerequisite_refs": ["node_set_three_properties", "node_representation_conversion"],
                        "node_refs": [
                            "node_parametric_set_analysis"
                        ],
                        "section_refs": ["§1.1 习题 1.1 综合运用", "§1.1 拓广探索"],
                        "status": "drafted"
                    }
                ]
            }

        elif aid == "task_author":
            return {
                "tasks": [
                    {
                        "task_id": "task_u1_01",
                        "unit_id": "unit_01_set_concept",
                        "source_refs": ["src_1_1_examples", "src_1_1_def_props", "src_1_1_practice"],
                        "objective": "依据集合元素的确定性判定给定对象总体能否构成集合，并说明客观理由",
                        "task_type": "classify",
                        "prompt": "【集合确定性综合判定】判断下列四组对象的全体是否能组成集合，并逐一写出判定理由：\n(1) 与定点 $A, B$ 等距离的所有点；\n(2) 高中学生中的游泳能手；\n(3) 方程 $x^2 - 3x + 2 = 0$ 的所有实数根；\n(4) 非常接近 $0$ 的所有实数。",
                        "prerequisite_refs": ["node_elem_and_set", "node_set_three_properties"],
                        "expected_evidence": "对每一组对象明确指出是否存在客观唯一的检验标准，能组成集合的需指出其元素是什么，不能组成集合的需指出哪个词导致界限模糊。",
                        "answer": "(1) 能组成集合；(2) 不能组成集合；(3) 能组成集合；(4) 不能组成集合。",
                        "worked_solution": "解题步骤：\n1. 分析(1)：平面或空间中点 $P$ 到定点 $A, B$ 距离相等等价于 $PA = PB$（平面内为线段 $AB$ 的垂直平分线，空间中为垂直平分面），标准客观明确，满足确定性，能组成集合。\n2. 分析(2)：『游泳能手』没有客观统一的量化界限，不满足确定性，不能组成集合。\n3. 分析(3)：解方程 $x^2 - 3x + 2 = 0$ 得 $x = 1$ 或 $x = 2$，元素确定为 $1$ 和 $2$，能组成集合。\n4. 分析(4)：『非常接近 $0$』缺乏精确度量标准，无法判定一个实数是否在范围内，不满足确定性，不能组成集合。",
                        "common_errors": [
                            "误认为(1)中点的个数无限就不能组成集合",
                            "仅写『能』或『不能』，未紧扣『元素确定性』给出判定理由"
                        ],
                        "error_reasons": [
                            "将『元素个数有限/无限』与『元素是否确定』混为一谈（无限个对象只要归属标准明确即可组成无限集）",
                            "未掌握集合确定性的规范表述模板"
                        ],
                        "hint_1": "判断一组对象能否组成集合，唯一标准是看它是否满足『确定性』，即给你任意一个对象，能否客观无歧义地判断它在不在总体内。",
                        "hint_2": "注意区分『客观几何/代数条件』（如 $PA=PB$、方程实数根）与『主观模糊形容词』（如能手、非常接近、高个子）。",
                        "hint_3": "对于(1)，满足 $PA=PB$ 的点虽然有无数个，但每个点是否满足 $PA=PB$ 是完全确定的；对于(2)和(4)，找出其中导致标准模糊的形容词即可作答。",
                        "retry_task": "变式训练：判断下列对象的全体能否组成集合并说明理由：① 小于 $10$ 的所有质数；② 班级里性格开朗的所有同学；③ 平面内到定点 $O$ 的距离等于 $5\\text{ cm}$ 的所有点。",
                        "boundary_note": "集合的元素个数可以是有限个（有限集），也可以是无限个（无限集），关键在于边界是否确定。"
                    },
                    {
                        "task_id": "task_u1_02",
                        "unit_id": "unit_01_set_concept",
                        "source_refs": ["src_1_1_num_sets", "src_1_1_practice", "src_1_1_exercises"],
                        "objective": "准确使用属于符号 ∈ 与不属于符号 ∉ 判定元素与五大常用数集及特定集合的关系",
                        "task_type": "classify",
                        "prompt": "【常用数集与属于关系专项（课本练习2 & 习题1.1第1题）】用符号『$\\in$』或『$\\notin$』填空，并简述每空的判断依据：\n(1) $0$ ___ $\\mathbf{N}$；$0$ ___ $\\mathbf{N}^*$；$-3$ ___ $\\mathbf{N}$；$0.5$ ___ $\\mathbf{Z}$；$\\sqrt{2}$ ___ $\\mathbf{Z}$；$\\frac{1}{3}$ ___ $\\mathbf{Q}$；$\\pi$ ___ $\\mathbf{R}$。\n(2) 若 $A = \\{x \\mid x^2 = x\\}$，则 $-1$ ___ $A$；若 $B = \\{x \\mid x^2 + x - 6 = 0\\}$，则 $3$ ___ $B$；若 $C = \\{x \\in \\mathbf{N} \\mid 1 \\le x \\le 10\\}$，则 $8$ ___ $C$，$9.1$ ___ $C$。",
                        "prerequisite_refs": ["node_belong_relation", "node_standard_number_sets"],
                        "expected_evidence": "不仅填对 ∈ 或 ∉ 符号，还需写出各数集的包含边界（如 0 属于自然数集但不属于正整数集）或将数值代入方程/不等式检验的过程。",
                        "answer": "(1) $\\in, \\notin, \\notin, \\notin, \\notin, \\in, \\in$；(2) $\\notin, \\notin, \\in, \\notin$。",
                        "worked_solution": "解题步骤：\n1. 第(1)组：$\\mathbf{N}$ 为非负整数集故 $0 \\in \\mathbf{N}$；$\\mathbf{N}^*$ 为正整数集不含 $0$ 故 $0 \\notin \\mathbf{N}^*$；$-3$ 为负数故 $-3 \\notin \\mathbf{N}$；$0.5$ 为有限小数故 $0.5 \\notin \\mathbf{Z}$；$\\sqrt{2}$ 为无理数故 $\\sqrt{2} \\notin \\mathbf{Z}$；$\\frac{1}{3}$ 为分数故 $\\frac{1}{3} \\in \\mathbf{Q}$；$\\pi$ 为实数（无理数）故 $\\pi \\in \\mathbf{R}$。\n2. 第(2)组：将 $x=-1$ 代入 $x^2=x$ 得 $1 \\neq -1$，故 $-1 \\notin A$；将 $x=3$ 代入 $x^2+x-6=0$ 得 $9+3-6=6 \\neq 0$，故 $3 \\notin B$；$8$ 是满足 $1 \\le 8 \\le 10$ 的自然数故 $8 \\in C$；$9.1$ 不是自然数（$9.1 \\notin \\mathbf{N}$）故 $9.1 \\notin C$。",
                        "common_errors": [
                            "将 $0$ 与 $\\mathbf{N}$、$\\mathbf{N}^*$ 的关系填反",
                            "误认为 $\\pi$ 是字母而不是具体实数，或误以为无限小数都不属于 $\\mathbf{Q}$",
                            "在判断 $9.1$ 与 $C$ 的关系时只看 $1 \\le 9.1 \\le 10$ 而漏看前置条件 $x \\in \\mathbf{N}$"
                        ],
                        "error_reasons": [
                            "对现行教材『$0$ 是自然数』的规定及正整数集右上角 $*$ 号剔除 $0$ 的含义记忆不牢",
                            "忽略了描述法竖线左侧 $x \\in \\mathbf{N}$ 对代表元素数集范围的硬性约束"
                        ],
                        "hint_1": "先背诵口诀：『$\\mathbf{N}$ 是自然含零集，$\\mathbf{N}^*$ 正整把零去，$\\mathbf{Z}$ 整 $\\mathbf{Q}$ 有 $\\mathbf{R}$ 实数』。",
                        "hint_2": "判断元素是否属于描述法集合 $\\{x \\in A \\mid P(x)\\}$ 时，必须同时满足两条：① 元素属于范围 $A$；② 代入条件 $P(x)$ 成立。",
                        "hint_3": "检查 $9.1$ 是否属于 $C = \\{x \\in \\mathbf{N} \\mid 1 \\le x \\le 10\\}$ 时，虽然 $1 \\le 9.1 \\le 10$ 成立，但 $9.1$ 是自然数吗？",
                        "retry_task": "变式训练：用 $\\in$ 或 $\\notin$ 填空：① $(-\\sqrt{3})^2$ ___ $\\mathbf{N}^*$；② $0.\\dot{3}$ ___ $\\mathbf{Q}$；③ 若 $M = \\{x \\in \\mathbf{Z} \\mid x^2 - 2 = 0\\}$，则 $\\sqrt{2}$ ___ $M$。",
                        "boundary_note": "无限循环小数（如 $0.\\dot{3} = \\frac{1}{3}$）属于有理数集 $\\mathbf{Q}$；无限不循环小数（如 $\\sqrt{2}, \\pi$）属于无理数，即属于 $\\mathbf{R}$ 但不属于 $\\mathbf{Q}$。"
                    },
                    {
                        "task_id": "task_u2_01",
                        "unit_id": "unit_02_set_representation",
                        "source_refs": ["src_1_1_roster", "src_1_1_practice", "src_1_1_exercises"],
                        "objective": "运用列举法规范表示有限数集与函数图象交点点集",
                        "task_type": "compute",
                        "prompt": "【列举法规范书写与数集/点集辨析（课本练习3 & 习题1.1第2题）】用列举法表示下列集合：\n(1) 大于 $1$ 且小于 $6$ 的整数；\n(2) $A = \\{x \\mid (x - 1)(x + 2) = 0\\}$；\n(3) $B = \\{x \\in \\mathbf{Z} \\mid -3 < 2x - 1 < 3\\}$；\n(4) 一次函数 $y = x + 3$ 与 $y = -2x + 6$ 图象的交点组成的集合 $D$。",
                        "prerequisite_refs": ["node_roster_method", "node_set_builder_method"],
                        "expected_evidence": "写出解方程、解不等式筛选整数、联立方程组求交点坐标的完整中间步骤，并用花括号正确区分实数元素与有序数对点元素。",
                        "answer": "(1) $\\{2, 3, 4, 5\\}$；(2) $A = \\{-2, 1\\}$；(3) $B = \\{0, 1\\}$；(4) $D = \\{(1, 4)\\}$。",
                        "worked_solution": "解题步骤：\n1. (1) 满足 $1 < x < 6$ 的整数依次为 $2, 3, 4, 5$，故表示为 $\\{2, 3, 4, 5\\}$。\n2. (2) 由 $(x-1)(x+2)=0$ 解得 $x=1$ 或 $x=-2$，故 $A = \\{-2, 1\\}$。\n3. (3) 解不等式 $-3 < 2x-1 < 3$ 得 $-2 < 2x < 4$，即 $-1 < x < 2$。因 $x \\in \\mathbf{Z}$，区间内的整数仅有 $0, 1$，故 $B = \\{0, 1\\}$。\n4. (4) 联立 $\\begin{cases} y = x + 3 \\\\ y = -2x + 6 \\end{cases}$ 解得 $\\begin{cases} x = 1 \\\\ y = 4 \\end{cases}$。因集合元素是『交点』，点用坐标 $(1, 4)$ 表示，故 $D = \\{(1, 4)\\}$。",
                        "common_errors": [
                            "第(1)题包含端点写成 $\\{1, 2, 3, 4, 5, 6\\}$",
                            "第(3)题忘记筛选整数，直接保留不等式而未列举出 $\\{0, 1\\}$",
                            "第(4)题将交点集合误写为 $\\{1, 4\\}$ 或 $\\{(1, 4), (4, 1)\\}$"
                        ],
                        "error_reasons": [
                            "审题时未注意『大于1且小于6』不包含端点 $1$ 和 $6$",
                            "混淆了『数集』与『点集』的代表元素形式，点集的元素必须加小括号写成有序实数对 $(x,y)$"
                        ],
                        "hint_1": "前(1)(2)(3)题的研究对象都是『数』，只需解出满足条件的全部整数或实数根，用逗号隔开放入花括号 $\\{\\}$ 内。",
                        "hint_2": "第(3)题先解不等式 $-3 < 2x - 1 < 3$ 求出 $x$ 的实数范围，再从中挑出所有整数 $x \\in \\mathbf{Z}$。",
                        "hint_3": "第(4)题的研究对象是『图象的交点』，平面上的一个点必须用坐标 $(x, y)$ 表示，因此花括号里面装的应该是一个带小括号的坐标！",
                        "retry_task": "变式训练：分别用列举法表示下列集合：① $M = \\{(x, y) \\mid x + y = 3, x \\in \\mathbf{N}^*, y \\in \\mathbf{N}^*\\}$；② 直线 $y = 2x - 1$ 与 $y = x + 1$ 的交点组成的集合。",
                        "boundary_note": "$\\{1, 4\\}$ 是含有两个实数的数集，而 $\\{(1, 4)\\}$ 是只含有一个点的点集，小括号绝不可省略！"
                    },
                    {
                        "task_id": "task_u2_02",
                        "unit_id": "unit_02_set_representation",
                        "source_refs": ["src_1_1_builder", "src_1_1_exercises"],
                        "objective": "运用描述法精确刻画函数值集合、自变量集合与不等式解集，并完成三种表示法的互译",
                        "task_type": "explain",
                        "prompt": "【描述法代表元素剖析与表示法互译（课本习题1.1第3、4题）】\n1. 用适当的方法表示下列集合，并指出每个集合的代表元素是什么：\n(1) 二次函数 $y = x^2 - 4$ 的函数值组成的集合 $A$；\n(2) 反比例函数 $y = \\frac{2}{x}$ 的自变量组成的集合 $B$；\n(3) 不等式 $3x \\ge 4 - 2x$ 的解集 $C$。\n2. 将集合 $E = \\{x \\in \\mathbf{N} \\mid 3 < x < 7\\}$ 改用列举法表示，将集合 $F = \\{2, 4, 6, 8, 10\\}$ 改用描述法表示。",
                        "prerequisite_refs": ["node_set_builder_method", "node_representation_conversion"],
                        "expected_evidence": "明确区分(1)的代表元素是函数值 y（范围 y >= -4）、(2)的代表元素是自变量 x（范围 x != 0），并写出解不等式及表示法互译的完整过程。",
                        "answer": "1.(1) $A = \\{y \\mid y = x^2 - 4\\} = \\{y \\mid y \\ge -4\\}$；(2) $B = \\{x \\mid y = \\frac{2}{x}\\} = \\{x \\in \\mathbf{R} \\mid x \\neq 0\\}$；(3) $C = \\{x \\mid x \\ge \\frac{4}{5}\\}$。\n2. $E = \\{4, 5, 6\\}$；$F = \\{x \\in \\mathbf{Z} \\mid x = 2k, 1 \\le k \\le 5, k \\in \\mathbf{Z}\\}$。",
                        "worked_solution": "解题步骤：\n1.(1) 研究对象是『函数值』，代表元素为 $y$。因对任意 $x \\in \\mathbf{R}$ 有 $x^2 \\ge 0$，故 $y = x^2 - 4 \\ge -4$，用描述法表示为 $A = \\{y \\mid y = x^2 - 4\\}$（即 $\\{y \\mid y \\ge -4\\}$）。\n1.(2) 研究对象是『自变量』，代表元素为 $x$。分式有意义需分母 $x \\neq 0$，故 $B = \\{x \\mid y = \\frac{2}{x}\\} = \\{x \\in \\mathbf{R} \\mid x \\neq 0\\}$。\n1.(3) 移项合并同类项得 $5x \\ge 4$，解得 $x \\ge \\frac{4}{5}$，故 $C = \\{x \\mid x \\ge \\frac{4}{5}\\}$。\n2. 满足 $3 < x < 7$ 的自然数有 $4, 5, 6$，故 $E = \\{4, 5, 6\\}$；$2, 4, 6, 8, 10$ 是前 $5$ 个正偶数，故 $F = \\{x \\in \\mathbf{Z} \\mid x = 2k, 1 \\le k \\le 5, k \\in \\mathbf{Z}\\}$（或 $\\{x \\in \\mathbf{N}^* \\mid x \\text{ 是偶数且 } x \\le 10\\}$）。",
                        "common_errors": [
                            "将二次函数的函数值集合误写成点集 $\\{(x, y) \\mid y = x^2 - 4\\}$ 或不带代表元素的 $\\{y = x^2 - 4\\}$",
                            "求反比例函数自变量集合时忘记分母 $x \\neq 0$ 的限制"
                        ],
                        "error_reasons": [
                            "没有理解描述法中竖线左侧代表元素的决定性作用：写 $y$ 代表函数值集（值域），写 $x$ 代表自变量集（定义域），写 $(x,y)$ 代表图象点集",
                            "对分式有意义的代数隐含条件不敏感"
                        ],
                        "hint_1": "写描述法的第一步永远是问自己：『题目让我求的是什么对象的集合？』求函数值就拿 $y$ 作代表元素，求自变量就拿 $x$ 作代表元素。",
                        "hint_2": "对于 $y = x^2 - 4$，因为 $x^2 \\ge 0$，你可以进一步算出函数值 $y$ 的最值范围；对于 $y = \\frac{2}{x}$，分母能等于 $0$ 吗？",
                        "hint_3": "对于集合 $F = \\{2, 4, 6, 8, 10\\}$，它们都是偶数（$x = 2k, k \\in \\mathbf{Z}$），并且满足 $2 \\le x \\le 10$。",
                        "retry_task": "变式训练：请说明下列三个集合各自的含义是否相同，并分别化简：① $M_1 = \\{x \\mid y = \\sqrt{x - 1}\\}$；② $M_2 = \\{y \\mid y = \\sqrt{x - 1}\\}$；③ $M_3 = \\{(x, y) \\mid y = \\sqrt{x - 1}\\}$。",
                        "boundary_note": "在描述法中，代表元素使用的字母本身可以更换（如 $\\{y \\mid y \\ge -4\\}$ 与 $\\{t \\mid t \\ge -4\\}$ 是同一个集合），但代表元素与右侧方程中自变量/因变量的对应关系绝不能颠倒！"
                    },
                    {
                        "task_id": "task_u3_01",
                        "unit_id": "unit_03_comprehensive_application",
                        "source_refs": ["src_1_1_def_props", "src_1_1_exercises"],
                        "objective": "运用按位数分类法列举组合自然数集，并通过互异性回代检验求解含参集合问题",
                        "task_type": "diagnose",
                        "prompt": "【集合综合运用与互异性诊断（课本习题1.1第3(2)题 & 含参互异性核心题）】\n(1) 用列举法表示集合：『由 $1, 2, 3$ 这三个数字抽出一部分或全部数字（没有重复）所组成的一切自然数』；\n(2) 已知集合 $A = \\{a + 2, (a + 1)^2, a^2 + 3a + 3\\}$，若 $1 \\in A$，求实数 $a$ 的值，并完整写出代回检验集合元素互异性的过程。",
                        "prerequisite_refs": ["node_set_three_properties", "node_parametric_set_analysis"],
                        "expected_evidence": "第(1)问需展示按一位数、两位数、三位数分类列举出全部15个数的过程；第(2)问需展示分三种情况解方程，并将解出的 a=-1, a=0, a=-2 逐一代回集合 A 写出三个元素具体数值、检验并舍去重复元素增根的过程。",
                        "answer": "(1) $\\{1, 2, 3, 12, 13, 21, 23, 31, 32, 123, 132, 213, 231, 312, 321\\}$；(2) $a = 0$（$a = -1$ 和 $a = -2$ 均因违反互异性舍去）。",
                        "worked_solution": "解题步骤：\n(1) 按自然数的位数分类列举：\n- 一位数（抽1个数字）：$1, 2, 3$（共3个）；\n- 两位数（抽2个不同数字）：$12, 13, 21, 23, 31, 32$（共6个）；\n- 三位数（抽3个不同数字）：$123, 132, 213, 231, 312, 321$（共6个）。\n故该集合为 $\\{1, 2, 3, 12, 13, 21, 23, 31, 32, 123, 132, 213, 231, 312, 321\\}$。\n(2) 由 $1 \\in A$ 分三类讨论：\n① 若 $a + 2 = 1$，则 $a = -1$。代回得 $(a+1)^2 = 0$，$a^2 + 3a + 3 = 1$，此时集合元素为 $1, 0, 1$，出现重复元素 $1$，违反互异性，舍去 $a = -1$；\n② 若 $(a + 1)^2 = 1$，则 $a = 0$ 或 $a = -2$。\n  - 当 $a = 0$ 时，代回得 $a + 2 = 2, (a+1)^2 = 1, a^2 + 3a + 3 = 3$，即 $A = \\{2, 1, 3\\}$，满足互异性，保留 $a = 0$；\n  - 当 $a = -2$ 时，代回得 $a + 2 = 0, (a+1)^2 = 1, a^2 + 3a + 3 = 1$，出现重复元素 $1$，违反互异性，舍去 $a = -2$；\n③ 若 $a^2 + 3a + 3 = 1$，解得 $a = -1$ 或 $a = -2$，由①②知均违反互异性，舍去。\n综上，实数 $a$ 的值为 $0$。",
                        "common_errors": [
                            "第(1)问误以为必须用完三个数字，只写了6个三位数，漏掉了一位数和两位数",
                            "第(2)问解出 $a = 0, -1, -2$ 后未代回原集合检验互异性，保留了增根 $-1$ 和 $-2$"
                        ],
                        "error_reasons": [
                            "审题时忽略了『抽出一部分或全部数字』中的『一部分』含义",
                            "缺乏对集合元素『互异性』的强制检验意识，误把方程的根直接当作集合参数的解"
                        ],
                        "hint_1": "第(1)问注意题干关键词『抽出一部分或全部数字』：抽1个数字组成一位数，抽2个数字组成两位数，抽3个数字组成三位数，按位数分类即可不重不漏。",
                        "hint_2": "第(2)问因为 $1 \\in A$，先分三种情况：$a + 2 = 1$，或 $(a + 1)^2 = 1$，或 $a^2 + 3a + 3 = 1$，解出所有可能的 $a$。",
                        "hint_3": "求出每个候选的 $a$ 值后，务必把 $a$ 代入 $a+2$、$(a+1)^2$、$a^2+3a+3$ 算出三个具体数字，只要有两个数字相等，该 $a$ 值就必须舍去！",
                        "retry_task": "变式训练：已知集合 $M = \\{2, a, b\\}$ 与集合 $N = \\{2a, 2, b^2\\}$ 相等（即 $M = N$），求实数 $a, b$ 的值。（提示：分类讨论 $\\begin{cases} a = 2a \\\\ b = b^2 \\end{cases}$ 或 $\\begin{cases} a = b^2 \\\\ b = 2a \\end{cases}$，解出后务必检验集合 $\\{2, a, b\\}$ 的互异性！）",
                        "boundary_note": "含参集合问题中，『代回检验互异性』是必写得分步骤，漏检必扣分！"
                    }
                ]
            }

        elif aid == "student_simulator":
            p = self.ensemble_persona or "median"
            persona_comments = {
                "strong": "试读画像[strong]：讲义对课本1.1节的概念、例题、练习与习题实现了100%无死角覆盖，特别是对描述法代表元素（数集 vs 点集 vs 值域集）的对比以及含参集合互异性三步检验法的剖析极具深度，康托尔集合论与罗素悖论背景有效加深了对描述法定义域限制的理解。",
                "median": "试读画像[median]：由初中方程与几何轨迹引入集合非常自然，常用数集表格帮我彻底分清了 N 与 N* 中 0 的归属；以前做习题1.1第3(2)题和交点集合题总是出错，通过讲义里的分类列举支架和点集反例对比，现在完全能独立做对了。",
                "weak": "试读画像[weak]：原本看课本时对描述法的竖线符号和习题里的填空题有些发怵，讲义把每一步推导都写得很清楚，没有『显然』之类的跳步，并且修复了原文扫描版的漏印符号，配有的三层提示让我在卡壳时能一步步顺着思路做出来。"
            }
            comment = persona_comments.get(p, persona_comments["median"])
            return {
                "reviews": [
                    {
                        "reviewer": f"student_sim:{p}",
                        "kind": "student_trial",
                        "target": "unit_01_set_concept",
                        "findings": [comment],
                        "stuck_points": [],
                        "decision": "pass",
                        "created_at": "2026-10-13 15:25:00"
                    },
                    {
                        "reviewer": f"student_sim:{p}",
                        "kind": "student_trial",
                        "target": "unit_02_set_representation",
                        "findings": [comment],
                        "stuck_points": [],
                        "decision": "pass",
                        "created_at": "2026-10-13 15:25:00"
                    },
                    {
                        "reviewer": f"student_sim:{p}",
                        "kind": "student_trial",
                        "target": "unit_03_comprehensive_application",
                        "findings": [comment],
                        "stuck_points": [],
                        "decision": "pass",
                        "created_at": "2026-10-13 15:25:00"
                    }
                ]
            }

        elif aid == "arbiter":
            return {
                "stop_flag": None,
                "units": []
            }

        elif aid == "converter_fixer":
            return {}

        return {}


def default_llm_factory(model_name: str, agent_id: str = "", persona: str = ""):
    """LLM 实例化工厂：优先使用 Mock 保证离线确定性，若有外置真实 LLM 则无缝桥接"""
    return MockAgentLLM(agent_id=agent_id, ensemble_persona=persona)


# =========================================================================
# 节点工厂核心实现
# =========================================================================

def make_agent_node(
    agent_id: str,
    registry: dict[str, Any],
    llm_factory: Callable = default_llm_factory,
    tool_binder: Callable = get_tools_by_names
) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """
    根据 agents.yaml 中的规格生成一个标准的 LangGraph 节点函数。
    强制校验：
    1. 只能写 writes 白名单声明的字段；
    2. 回流时自动注入 repair_context；
    3. 支持 ensemble: N 的多 persona 试读分支；
    4. 累加 retry_counts。
    """
    spec = registry["agents"][agent_id]
    reads = spec.get("reads", [])
    writes = spec.get("writes", [])
    ensemble_size = spec.get("ensemble", 1)

    def agent_node(state: GraphState, config: RunnableConfig = None) -> dict[str, Any]:
        discipline = state.discipline or "math"
        disc_cfg = load_discipline_config(discipline)
        prompt_tmpl = load_prompt_template(spec.get("prompt_file", ""))
        tools = tool_binder(spec.get("tools", []))

        # 检查是否为门禁失败后的回流调用
        repair_context = build_repair_context(state, agent_id)

        # 提取声明读取的 inputs
        inputs = {k: getattr(state, k, None) for k in reads}
        inputs_serialized = serialize_for_prompt(inputs)

        # 针对 ensemble 机制（如 student_simulator）
        if ensemble_size > 1 and agent_id == "student_simulator":
            personas = ["strong", "median", "weak"][:ensemble_size]
            all_reviews = []
            for p in personas:
                llm = llm_factory(spec.get("model", ""), agent_id=agent_id, persona=p)
                render_vars = {
                    **inputs_serialized,
                    "persona": p,
                    "discipline_patch": disc_cfg.get("prompt_patch", ""),
                    "repair_context": json.dumps(repair_context, ensure_ascii=False)
                }
                # 安全 format
                prompt_text = prompt_tmpl
                for k, v in render_vars.items():
                    prompt_text = prompt_text.replace(f"{{{k}}}", str(v))

                raw_result = llm.invoke(prompt_text)
                patch = parse_patch(raw_result, allowed_keys=writes)
                if "reviews" in patch:
                    all_reviews.extend(patch["reviews"])

            res_patch = {"reviews": all_reviews}
        else:
            llm = llm_factory(spec.get("model", ""), agent_id=agent_id)
            render_vars = {
                **inputs_serialized,
                "discipline_patch": disc_cfg.get("prompt_patch", ""),
                "repair_context": json.dumps(repair_context, ensure_ascii=False)
            }
            prompt_text = prompt_tmpl
            for k, v in render_vars.items():
                prompt_text = prompt_text.replace(f"{{{k}}}", str(v))

            raw_result = llm.invoke(prompt_text)
            res_patch = parse_patch(raw_result, allowed_keys=writes)

        # 记录 retry_counts
        res_patch["retry_counts"] = {agent_id: 1}
        return res_patch

    agent_node.__name__ = agent_id
    return agent_node


def make_gate_node(gate: Gate) -> Callable[[GraphState], dict[str, Any]]:
    """
    纯门禁节点工厂：
    执行门禁的所有确定性校验与可选 rubric，
    产出 GateResult，绝不修改内容状态本身。
    """
    def gate_node(state: GraphState) -> dict[str, Any]:
        result = gate.evaluate(state)
        # 若检出严重致命错误 P0_stop，同步置位 stop_flag
        stop_val = None
        if any(f.get("severity") == "P0_stop" for f in result.failures):
            stop_val = f"P0_stop at {gate.name}: {result.failures[0].get('msg')}"

        res = {"gate_results": [result]}
        if stop_val:
            res["stop_flag"] = stop_val
        return res

    gate_node.__name__ = f"gate_{gate.name}"
    return gate_node
