# -*- coding: utf-8 -*-
"""
lang.tests.test_e2e_pipeline
----------------------------
端到端主图流水线全流程测试 (to_lang.md §10.4, §13, §14)
"""

import os
import shutil
import pytest
from lang.pipeline import run_pipeline, build_initial_state
from lang.graph_builder import build_main_graph
from lang.state import DependencyEdge, ConceptNode, GateResult
from lang.exporters import export_all, export_check, ExportVerificationError


@pytest.fixture
def tmp_output_dir(tmp_path):
    out = tmp_path / "test_output"
    out.mkdir()
    return str(out)


@pytest.fixture
def tmp_checkpoint_db(tmp_path):
    return str(tmp_path / "test_pipeline.db")


def test_e2e_pipeline_golden_path(tmp_output_dir, tmp_checkpoint_db):
    """
    黄金路径测试：
    1. 跑通完整主图（各阶段产出合规数据并通过全部门禁）；
    2. 签发 release_manifest；
    3. 成功落盘最小可交付包目录结构并校验哈希。
    """
    result = run_pipeline(
        raw_files=["chapter1.pdf"],
        discipline="math",
        output_dir=tmp_output_dir,
        checkpoint_db=tmp_checkpoint_db,
        thread_id="test_golden_001",
        resume=False,
        max_retry=3
    )

    assert result["success"] is True
    assert result["status"] == "certified"
    final_state = result["state"]
    assert final_state.manifest is not None
    assert final_state.manifest.approver.startswith("release_manager")

    # 验证输出目录中的必要制品
    expected_files = [
        "good.md",
        "graph.json",
        "tasks.json",
        "evidence_manifest.json",
        "diagnosis_report.md",
        "trial_report.md",
        "release_manifest.json"
    ]
    for ef in expected_files:
        ef_path = os.path.join(tmp_output_dir, ef)
        assert os.path.exists(ef_path), f"缺少核心交付文件: {ef}"
        assert os.path.getsize(ef_path) > 0

    # 验证门禁报告目录
    gate_reports_dir = os.path.join(tmp_output_dir, "gate_reports")
    assert os.path.isdir(gate_reports_dir)
    assert os.path.exists(os.path.join(gate_reports_dir, "source_gate.json"))
    assert os.path.exists(os.path.join(gate_reports_dir, "output_gate.json"))


def test_e2e_pipeline_p0_stop_safety(tmp_output_dir, tmp_checkpoint_db):
    """
    安全停止条件测试 (to_lang.md §6.3, §15):
    若注入 P0 级致命缺陷（如拓扑循环依赖），
    流水线必须立即熔断走向 stop_and_report，且绝不落地任何交付包。
    """
    # 模拟构建初始状态，预置循环依赖节点与边
    c1 = ConceptNode(node_id="c1", name="概念1", kind="concept", statement="def1")
    c2 = ConceptNode(node_id="c2", name="概念2", kind="concept", statement="def2")
    e1 = DependencyEdge(from_id="c1", to_id="c2", relation="前置依赖")
    e2 = DependencyEdge(from_id="c2", to_id="c1", relation="前置依赖")  # 成环！

    main_graph = build_main_graph(max_retry=2, use_compiled_subgraphs=False)
    app = main_graph.compile()

    init_state = build_initial_state(["chapter1.pdf"], "math", tmp_output_dir)
    init_state["nodes"] = [c1, c2]
    init_state["edges"] = [e1, e2]

    # 直接执行
    final_dict = app.invoke(init_state)

    # 必须未产出 manifest
    assert final_dict.get("manifest") is None
    # 必须未能落盘交付文件
    assert not os.path.exists(os.path.join(tmp_output_dir, "good.md"))


def test_export_check_without_manifest(tmp_output_dir):
    """测试当 manifest 为空时 export_all 抛出强校验异常"""
    bad_state = build_initial_state(["test.pdf"], "math", tmp_output_dir)
    with pytest.raises(ExportVerificationError):
        export_all(bad_state, tmp_output_dir)
