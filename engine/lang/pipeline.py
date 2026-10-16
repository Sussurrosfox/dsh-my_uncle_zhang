# -*- coding: utf-8 -*-
"""
lang.pipeline
-------------
LangGraph 自动化自学教材教研流水线核心执行入口 (to_lang.md §14, §16)
支持:
  1. 端到端状态机编译与驱动
  2. SqliteSaver 生产级断点恢复 (Checkpointer)
  3. 最小可交付包落盘验证 (export_all)
  4. 命令行交互 (CLI)
"""

from __future__ import annotations
import os
import sys
import argparse
import sqlite3
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from lang.state import GraphState
from lang.graph_builder import build_main_graph
from lang.exporters import export_all, ExportVerificationError


def get_default_output_dir(raw_files: list[str]) -> str:
    """计算默认输出目录：在输入文件的目录下建立的子文件夹 <string>_uncle，其中 string 为输入文件名"""
    if not raw_files:
        return "output_uncle"
    first_file = raw_files[0]
    parent_dir = os.path.dirname(first_file)
    base_name = os.path.basename(first_file)
    stem, _ = os.path.splitext(base_name)
    string = stem if stem else base_name
    folder_name = f"{string}_uncle"
    return os.path.join(parent_dir, folder_name) if parent_dir else folder_name


def build_initial_state(
    raw_files: list[str],
    discipline: str = "math",
    output_dir: str | None = None
) -> dict[str, Any]:
    """构建主图启动初始状态字典"""
    if not output_dir or output_dir in ("output", "release_deliverables"):
        output_dir = get_default_output_dir(raw_files)

    return {
        "raw_files": raw_files,
        "discipline": discipline,
        "good_md_path": os.path.join(output_dir, "good.md"),
        "sources": [],
        "nodes": [],
        "edges": [],
        "units": [],
        "tasks": [],
        "diagnoses": [],
        "reviews": [],
        "gate_results": [],
        "retry_counts": {},
        "current_stage": "sg1_source",
        "good_md": "",
        "manifest": None,
        "stop_flag": None
    }


def run_pipeline(
    raw_files: list[str],
    discipline: str = "math",
    output_dir: str | None = None,
    checkpoint_db: str = "pipeline_state.db",
    thread_id: str = "run_001",
    resume: bool = False,
    max_retry: int = 3,
    use_compiled_subgraphs: bool = True
) -> dict[str, Any]:
    """
    运行或恢复自学教材重构流水线。
    """
    if not output_dir or output_dir in ("output", "release_deliverables"):
        output_dir = get_default_output_dir(raw_files)

    print(f"=== [Pipeline] 启动 LangGraph 教学流水线 ===")
    print(f"  学科: {discipline}")
    print(f"  原始输入: {raw_files}")
    print(f"  交付目录: {output_dir}")
    print(f"  检查点数据库: {checkpoint_db} (线程: {thread_id}, 恢复模式: {resume})")

    # 1. 初始化 SQLite Checkpointer
    conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
    try:
        checkpointer = SqliteSaver(conn)

        # 2. 组装图并编译
        main_graph = build_main_graph(
            max_retry=max_retry,
            use_compiled_subgraphs=use_compiled_subgraphs
        )
        app = main_graph.compile(checkpointer=checkpointer)

        # 3. 配置运行时 thread_id
        config = {"configurable": {"thread_id": thread_id}}

        # 4. 执行状态机推进
        if resume:
            print(f"  [*] 尝试从检查点 {thread_id} 恢复...")
            # 恢复模式下传入空状态字典，由 checkpointer 载入历史快照
            result_state_dict = app.invoke(None, config=config)
        else:
            init_state = build_initial_state(raw_files, discipline, output_dir)
            result_state_dict = app.invoke(init_state, config=config)

        # 转换字典为 GraphState Pydantic 模型
        final_state = GraphState(**result_state_dict) if isinstance(result_state_dict, dict) else result_state_dict

        # 5. 校验收官结果
        if final_state.stop_flag or not final_state.manifest:
            print("\n[!] 流水线未能签发版本发布 (触发停止条件或熔断)。")
            print(f"    停止标识: {final_state.stop_flag}")
            print("    [安全约束] 拒绝落盘最小可交付包。")
            return {
                "success": False,
                "status": "stopped",
                "stop_flag": final_state.stop_flag,
                "state": final_state
            }

        # 6. 成功通过所有门禁，落盘最小可交付包
        print("\n[+] 所有门禁通过，开始机械落盘最小可交付包...")
        try:
            written_files = export_all(final_state, output_dir)
            print(f"[OK] 成功交付！共落盘 {len(written_files)} 个核心制品至 {output_dir}")
            for path, sha in written_files.items():
                print(f"    - {os.path.basename(path)}: {sha[:12]}...")
            return {
                "success": True,
                "status": "certified",
                "manifest": final_state.manifest,
                "written_files": written_files,
                "state": final_state
            }
        except ExportVerificationError as e:
            print(f"[FAIL] 交付包导出强校验失败: {e}")
            return {
                "success": False,
                "status": "export_error",
                "error": str(e),
                "state": final_state
            }
    finally:
        conn.close()


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description="LangGraph 自动化自学教材教研流水线")
    parser.add_argument("--input", "-i", nargs="+", default=[], help="输入原材料路径（PDF 或 Markdown）")
    parser.add_argument("--discipline", "-d", default="math", choices=["math", "physics"], help="学科领域")
    parser.add_argument("--output", "-o", default=None, help="最小可交付包输出目录（缺省为在输入文件目录下建立的 string_uncle）")
    parser.add_argument("--checkpoint-db", default="pipeline_state.db", help="SQLite 检查点数据库文件")
    parser.add_argument("--thread-id", default="session_01", help="会话线程标识")
    parser.add_argument("--resume", action="store_true", help="是否从断点恢复执行")
    parser.add_argument("--max-retry", type=int, default=3, help="门禁最大重试次数")

    args = parser.parse_args()

    if not args.resume and not args.input:
        parser.error("--input / -i 是必填参数（当非 --resume 模式时）")

    res = run_pipeline(
        raw_files=args.input,
        discipline=args.discipline,
        output_dir=args.output,
        checkpoint_db=args.checkpoint_db,
        thread_id=args.thread_id,
        resume=args.resume,
        max_retry=args.max_retry
    )

    if not res["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
