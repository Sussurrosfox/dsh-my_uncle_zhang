# -*- coding: utf-8 -*-
"""
lang.tests.test_state_and_reducers
----------------------------------
测试 GraphState 模型及自定义 Reducer 逻辑 (to_lang.md §10.1)
"""

import pytest
from lang.state import (
    GraphState, SourceNode, ConceptNode, DependencyEdge, Task,
    merge_by_key, merge_edges, merge_retry_counts
)


def test_merge_by_key_idempotence_and_update():
    """测试基于 key_field 的归约幂等性与字段覆写"""
    reducer = merge_by_key("node_id")
    c1 = ConceptNode(node_id="c1", name="集合", kind="concept", statement="集合的原始定义")
    c2 = ConceptNode(node_id="c2", name="元素", kind="concept", statement="元素的定义")
    
    # 初始合并
    merged = reducer([c1], [c2])
    assert len(merged) == 2
    assert {n.node_id for n in merged} == {"c1", "c2"}

    # 更新 c1
    c1_updated = ConceptNode(node_id="c1", name="集合", kind="concept", statement="集合的现代定义")
    merged2 = reducer(merged, [c1_updated])
    assert len(merged2) == 2
    c1_res = next(n for n in merged2 if n.node_id == "c1")
    assert c1_res.statement == "集合的现代定义"


def test_merge_edges():
    """测试有向依赖边的去重与归约"""
    e1 = DependencyEdge(from_id="c1", to_id="c2", relation="前置依赖")
    e2 = DependencyEdge(from_id="c2", to_id="c3", relation="前置依赖")
    
    # 初始
    merged = merge_edges([], [e1, e2])
    assert len(merged) == 2

    # 重复加入 e1 (完全相同或关系相同)
    e1_dup = DependencyEdge(from_id="c1", to_id="c2", relation="前置依赖")
    merged2 = merge_edges(merged, [e1_dup])
    assert len(merged2) == 2

    # 更新 relation
    e1_modified = DependencyEdge(from_id="c1", to_id="c2", relation="动机铺垫")
    merged3 = merge_edges(merged2, [e1_modified])
    assert len(merged3) == 3  # (c1, c2, 前置依赖) 与 (c1, c2, 动机铺垫) 形成并存边
    relations = {e.relation for e in merged3 if e.from_id == "c1" and e.to_id == "c2"}
    assert relations == {"前置依赖", "动机铺垫"}


def test_merge_retry_counts():
    """测试重试计数器累加与归零"""
    current = {"writer": 1, "task_author": 2}
    update = {"writer": 1, "task_author": 0}  # writer +1, task_author 归零
    
    merged = merge_retry_counts(current, update)
    assert merged["writer"] == 2
    assert merged["task_author"] == 0


def test_graph_state_instantiation():
    """测试 GraphState 实例化"""
    state = GraphState(
        raw_files=["sample.pdf"],
        discipline="math",
        good_md_path="output/good.md"
    )
    assert len(state.sources) == 0
    assert len(state.nodes) == 0
    assert state.stop_flag is None
    assert state.manifest is None
