"""构建快照与内容 hash 工具。

设计不变量：
- compute_state_hash 只覆盖【内容字段】（来源/诊断/图/单元/任务/试读/正文），
  绝不覆盖 gate_results、manifest、build_id、retry_counts 等过程字段。
  这样门禁可以把"自己运行时刻的 hash"写进 GateResult，事后任何人都能复算校验。
- 同一内容必须得到同一 hash（canonical JSON：排序键、紧凑分隔符、UTF-8）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

RULESET_VERSION = "gates-2.0.0"
EXECUTOR_VERSION = "my_uncle_zhang-2.0.0"

# 参与快照的内容字段（GraphState 上的属性名）。
# 注意：故意不含 gate_results / manifest / stop_flag / retry_counts / build_id。
CONTENT_FIELDS = [
    "sources",
    "diagnoses",
    "nodes",
    "edges",
    "units",
    "tasks",
    "reviews",
    "good_md",
]


def _canonical(obj: Any) -> str:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _dump_field(value: Any) -> Any:
    """pydantic 模型列表 → dict 列表；其余原样。"""
    if isinstance(value, list):
        out = []
        for item in value:
            if hasattr(item, "model_dump"):
                out.append(item.model_dump())
            else:
                out.append(item)
        return out
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def new_build_id() -> str:
    return "build-" + uuid.uuid4().hex[:16]


def _get_field_val(state: Any, field: str) -> Any:
    if isinstance(state, dict):
        if field not in state:
            raise AttributeError(
                f"GraphState 缺少快照字段 {field}；若字段改名请同步 CONTENT_FIELDS"
            )
        return state[field]
    if not hasattr(state, field):
        raise AttributeError(
            f"GraphState 缺少快照字段 {field}；若字段改名请同步 CONTENT_FIELDS"
        )
    return getattr(state, field)


def compute_state_hash(state: Any) -> str:
    payload = {
        field: _dump_field(_get_field_val(state, field))
        for field in CONTENT_FIELDS
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def compute_artifact_hashes(state: Any) -> dict:
    """分制品 hash，便于 manifest 精确列示。"""
    return {
        field: hashlib.sha256(
            _canonical(_dump_field(_get_field_val(state, field))).encode("utf-8")
        ).hexdigest()
        for field in CONTENT_FIELDS
    }
