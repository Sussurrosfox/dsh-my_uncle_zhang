# -*- coding: utf-8 -*-
"""
langgraph-courseware runner.py
------------------------------
DeepSeek Harness 插件 Python 桥接调度器。
负责执行 LangGraph 自学教材教研流水线、门禁判定、状态机可视化与断点快照审计。
"""

from __future__ import annotations
import os
import io
import sys
import json
import argparse
import sqlite3
import traceback
import contextlib
from typing import Any

# 1. 动态自适应寻址引擎路径
current_dir = os.path.dirname(os.path.abspath(__file__))
plugin_root = os.path.dirname(current_dir)
engine_dir = os.path.join(plugin_root, "engine")

def setup_sys_path(project_root: str | None = None):
    # 优先使用传入的 project_root 或当前工作目录（若包含 lang 模块）
    search_paths = []
    if project_root and os.path.exists(os.path.join(project_root, "lang")):
        search_paths.append(project_root)
    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, "lang")):
        search_paths.append(cwd)
    # 回退到插件内置 engine 目录
    if os.path.exists(os.path.join(engine_dir, "lang")):
        search_paths.append(engine_dir)

    for p in search_paths:
        if p not in sys.path:
            sys.path.insert(0, p)

def action_visualize(args) -> dict[str, Any]:
    from lang.graph_builder import build_main_graph
    try:
        main_graph = build_main_graph(max_retry=args.max_retry)
        app = main_graph.compile()
        mermaid_code = app.get_graph().draw_mermaid()
        return {
            "success": True,
            "format": "mermaid",
            "mermaid": mermaid_code,
            "message": "主图 Mermaid 拓扑图生成成功"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

def action_status(args) -> dict[str, Any]:
    checkpoint_db = os.path.abspath(args.checkpoint_db)
    if not os.path.exists(checkpoint_db):
        return {
            "success": False,
            "exists": False,
            "message": f"检查点数据库不存在: {checkpoint_db}"
        }

    try:
        conn = sqlite3.connect(checkpoint_db)
        cursor = conn.cursor()
        # 查询 checkpoints
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        info = {
            "db_path": checkpoint_db,
            "tables": tables,
            "thread_id": args.thread_id,
            "checkpoints_count": 0,
            "recent_stages": []
        }

        if "checkpoints" in tables:
            cursor.execute("SELECT count(*) FROM checkpoints WHERE thread_id = ?", (args.thread_id,))
            info["checkpoints_count"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT checkpoint_id, parent_checkpoint_id FROM checkpoints WHERE thread_id = ? ORDER BY rowid DESC LIMIT 10",
                (args.thread_id,)
            )
            rows = cursor.fetchall()
            info["recent_checkpoints"] = [{"id": r[0], "parent": r[1]} for r in rows]

        conn.close()
        return {
            "success": True,
            "exists": True,
            "status": info
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return obj.model_dump()
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()
    return str(obj)


def action_run(args) -> dict[str, Any]:
    from lang.pipeline import run_pipeline

    is_resume = bool(args.resume or args.action == "resume")
    raw_files = args.input or []
    if not is_resume and not raw_files:
        return {
            "success": False,
            "error": "未提供输入原材料文件 (raw_files 为空)"
        }

    output_dir = args.output
    if not output_dir or output_dir in ("release_deliverables", "output"):
        from lang.pipeline import get_default_output_dir
        output_dir = get_default_output_dir(raw_files)

    buf = io.StringIO()
    err_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err_buf):
            result = run_pipeline(
                raw_files=raw_files,
                discipline=args.discipline,
                output_dir=output_dir,
                checkpoint_db=args.checkpoint_db,
                thread_id=args.thread_id,
                resume=is_resume,
                max_retry=args.max_retry
            )

        output_res = {
            "success": result.get("success", False),
            "status": result.get("status"),
            "stop_flag": result.get("stop_flag"),
            "logs": buf.getvalue().strip(),
        }
        stderr_logs = err_buf.getvalue().strip()
        if stderr_logs:
            output_res["stderr_logs"] = stderr_logs

        if "manifest" in result and result["manifest"]:
            output_res["manifest"] = (
                result["manifest"].model_dump()
                if hasattr(result["manifest"], "model_dump")
                else (result["manifest"].dict() if hasattr(result["manifest"], "dict") else result["manifest"])
            )
        if "written_files" in result:
            output_res["written_files"] = result["written_files"]
        if result.get("error"):
            output_res["error"] = str(result["error"])

        if "state" in result and result["state"]:
            st = result["state"]
            output_res["gate_summary"] = [
                {
                    "gate": gr.gate,
                    "passed": gr.passed,
                    "decided_by": gr.decided_by,
                    "failures_count": len(gr.failures)
                }
                for gr in getattr(st, "gate_results", [])
            ]
            output_res["units_count"] = len(getattr(st, "units", []))
            output_res["nodes_count"] = len(getattr(st, "nodes", []))
            output_res["tasks_count"] = len(getattr(st, "tasks", []))

        return output_res
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "logs": buf.getvalue().strip(),
        }


def action_resume(args) -> dict[str, Any]:
    args.resume = True
    return action_run(args)

def action_gate(args) -> dict[str, Any]:
    from lang.gates.registry import GATES, GATES_BY_NAME
    from lang.state import GraphState

    gate_name = args.gate
    state_file = args.state_file

    if state_file and os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = GraphState(**data)
    else:
        # 使用空状态或基础模型进行静态校验测试
        from lang.pipeline import build_initial_state
        state = GraphState(**build_initial_state(raw_files=["placeholder.md"]))

    results = []
    if gate_name == "all":
        gates_to_run = GATES
    elif gate_name in GATES_BY_NAME:
        gates_to_run = [GATES_BY_NAME[gate_name]]
    else:
        return {
            "success": False,
            "error": f"未知门禁名称: {gate_name}。可用门禁: {list(GATES_BY_NAME.keys()) + ['all']}"
        }

    all_passed = True
    for g in gates_to_run:
        res = g.evaluate(state)
        if not res.passed:
            all_passed = False
        results.append({
            "gate": res.gate,
            "passed": res.passed,
            "failures": res.failures,
            "decided_by": res.decided_by,
            "decided_at": res.decided_at
        })

    return {
        "success": True,
        "all_passed": all_passed,
        "results": results
    }

def action_test(args) -> dict[str, Any]:
    import pytest
    test_dir = os.path.join(plugin_root, "engine", "lang", "tests")
    if not os.path.exists(test_dir):
        test_dir = os.path.join(os.getcwd(), "lang", "tests")

    buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err_buf):
        ret = pytest.main([test_dir, "-q"])

    res: dict[str, Any] = {
        "success": (ret == 0),
        "exit_code": int(ret),
        "message": "全量单测与黄金路径通过" if ret == 0 else "测试未全量通过",
        "logs": buf.getvalue().strip(),
    }
    stderr_logs = err_buf.getvalue().strip()
    if stderr_logs:
        res["stderr_logs"] = stderr_logs
    return res

def main():
    parser = argparse.ArgumentParser(description="LangGraph Courseware Bridge Runner")
    parser.add_argument("--action", required=True, choices=["run", "resume", "status", "visualize", "gate", "test"])
    parser.add_argument("--project-root", default=None, help="项目根目录")
    parser.add_argument("--input", "-i", nargs="*", default=[], help="原始原材料文件")
    parser.add_argument("--discipline", "-d", default="math", choices=["math", "physics"])
    parser.add_argument("--output", "-o", default=None, help="最小可交付包输出目录（缺省为在输入文件目录下建立的 string_uncle）")
    parser.add_argument("--checkpoint-db", default="pipeline_state.db")
    parser.add_argument("--thread-id", default="session_01")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-retry", type=int, default=3)
    parser.add_argument("--gate", default="all")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--json-output", action="store_true", default=True)

    args = parser.parse_args()
    setup_sys_path(args.project_root)

    dispatch = {
        "run": action_run,
        "resume": action_resume,
        "status": action_status,
        "visualize": action_visualize,
        "gate": action_gate,
        "test": action_test,
    }

    handler = dispatch.get(args.action)
    result = handler(args)

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    else:
        print(result)

if __name__ == "__main__":
    main()
