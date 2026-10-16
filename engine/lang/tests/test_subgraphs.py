# -*- coding: utf-8 -*-
"""
lang.tests.test_subgraphs
-------------------------
测试 SG1 ~ SG5 子图的构建与执行 (to_lang.md §5, §10.3)
"""

import pytest
from lang.state import GraphState, SourceNode
from lang.node_factory import load_agents_registry
from lang.subgraphs.sg1_source import build_sg1_subgraph
from lang.subgraphs.sg2_diagnosis import build_sg2_subgraph
from lang.subgraphs.sg3_structure import build_sg3_subgraph
from lang.subgraphs.sg4_pedagogy import build_sg4_subgraph
from lang.subgraphs.sg5_feedback import build_sg5_subgraph


def test_sg1_source_subgraph_execution():
    """测试 SG1 来源核验子图单轮执行"""
    reg = load_agents_registry()
    sg1 = build_sg1_subgraph(registry=reg, max_retry=2).compile()

    init_state = {
        "raw_files": ["sample_chapter.pdf"],
        "discipline": "math",
        "good_md_path": "out.md",
        "sources": [],
        "retry_counts": {}
    }

    res = sg1.invoke(init_state)
    assert "sources" in res
    assert len(res["sources"]) > 0
    # evidence_builder + source_verifier 产出的 sources 必须被标记 verified
    for s in res["sources"]:
        assert s.transcription_status == "verified"


def test_sg2_diagnosis_subgraph_execution():
    """测试 SG2 防自学诊断子图单轮执行"""
    reg = load_agents_registry()
    sg2 = build_sg2_subgraph(registry=reg, max_retry=2).compile()

    init_state = {
        "raw_files": ["sample_chapter.pdf"],
        "discipline": "math",
        "good_md_path": "out.md",
        "diagnoses": [],
        "retry_counts": {}
    }

    res = sg2.invoke(init_state)
    assert "diagnoses" in res
    assert len(res["diagnoses"]) > 0
    for d in res["diagnoses"]:
        assert d.evidence is not None
        assert len(d.evidence) > 5


def test_sg3_structure_subgraph_execution():
    """测试 SG3 结构重建子图单轮执行"""
    reg = load_agents_registry()
    sg3 = build_sg3_subgraph(registry=reg, max_retry=2).compile()

    init_state = {
        "raw_files": ["sample_chapter.pdf"],
        "discipline": "math",
        "good_md_path": "out.md",
        "nodes": [],
        "edges": [],
        "retry_counts": {}
    }

    res = sg3.invoke(init_state)
    assert len(res["nodes"]) > 0
    assert len(res["edges"]) >= 0


def test_sg4_pedagogy_subgraph_execution():
    """测试 SG4 单元设计与正文撰写子图单轮执行"""
    reg = load_agents_registry()
    sg4 = build_sg4_subgraph(registry=reg, max_retry=2).compile()

    init_state = {
        "raw_files": ["sample_chapter.pdf"],
        "discipline": "math",
        "good_md_path": "out.md",
        "units": [],
        "good_md": "",
        "retry_counts": {}
    }

    res = sg4.invoke(init_state)
    assert len(res["units"]) > 0
    assert len(res["good_md"]) > 0


def test_sg5_feedback_subgraph_execution():
    """测试 SG5 任务与反馈子图单轮执行"""
    reg = load_agents_registry()
    sg5 = build_sg5_subgraph(registry=reg, max_retry=2).compile()

    init_state = {
        "raw_files": ["sample_chapter.pdf"],
        "discipline": "math",
        "good_md_path": "out.md",
        "tasks": [],
        "retry_counts": {}
    }

    res = sg5.invoke(init_state)
    assert len(res["tasks"]) > 0
    for t in res["tasks"]:
        assert t.hint_1 and t.hint_2 and t.hint_3
        assert t.answer is not None
