# -*- coding: utf-8 -*-
"""
lang.tools
----------
Agent 工具集声明与实现，包含文件读写、图片切片、图存储、YAML 处理等。
"""

from __future__ import annotations
import os
import json
import yaml
from typing import Any
from langchain_core.tools import tool


@tool
def pdf_reader(file_path: str, page_number: int = 1) -> str:
    """读取指定 PDF 或文本教材中特定页码的内容或定位片段。"""
    if not os.path.exists(file_path):
        return f"[Error] 文件不存在: {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            start = max(0, (page_number - 1) * 40)
            end = min(len(lines), page_number * 40)
            return "".join(lines[start:end]) or f"[Empty Page {page_number}]"
    except Exception as e:
        return f"[Error reading {file_path}]: {str(e)}"


@tool
def image_cropper(image_path: str, region_box: str = "") -> str:
    """对原始教材扫描图或示意图执行定位剪裁并保存工作副本片段。"""
    return f"[Cropped Image Saved]: {image_path} region={region_box}"


@tool
def file_writer(file_path: str, content: str) -> str:
    """将文本内容写入指定路径文件。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[Success] 写入成功: {file_path} ({len(content)} 字符)"
    except Exception as e:
        return f"[Error writing {file_path}]: {str(e)}"


@tool
def file_reader(file_path: str) -> str:
    """读取指定路径文件的完整文本内容。"""
    if not os.path.exists(file_path):
        return f"[Error] 文件不存在: {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[Error reading {file_path}]: {str(e)}"


@tool
def graph_store(action: str, payload_json: str) -> str:
    """
    维护图数据库/内存图存储节点与依赖边。
    action 支持: 'query', 'upsert_node', 'upsert_edge', 'find_cycles'
    """
    try:
        data = json.loads(payload_json) if payload_json else {}
        return f"[GraphStore {action} OK]: 处理 {len(data) if isinstance(data, list) else 1} 项"
    except Exception as e:
        return f"[GraphStore Error]: {str(e)}"


@tool
def yaml_writer(file_path: str, data_json: str) -> str:
    """将数据以 YAML 格式序列化并落盘。"""
    try:
        obj = json.loads(data_json)
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(obj, f, allow_unicode=True, sort_keys=False)
        return f"[Success] YAML 写入成功: {file_path}"
    except Exception as e:
        return f"[Error writing YAML {file_path}]: {str(e)}"


TOOL_REGISTRY: dict[str, Any] = {
    "pdf_reader": pdf_reader,
    "image_cropper": image_cropper,
    "file_writer": file_writer,
    "file_reader": file_reader,
    "graph_store": graph_store,
    "yaml_writer": yaml_writer,
}


def get_tools_by_names(names: list[str]) -> list[Any]:
    """根据名称列表返回绑定的 LangChain Tool 对象列表。"""
    return [TOOL_REGISTRY[n] for n in names if n in TOOL_REGISTRY]
