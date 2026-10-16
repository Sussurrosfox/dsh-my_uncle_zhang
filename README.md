# my_uncle_zhang

LangGraph 自动化自学教材教研流水线 DeepSeek Harness 插件 (`my_uncle_zhang`)。

---

## 1. 概述

本插件将工作区 `lang/` 中基于 **LangGraph** 状态机驱动的自学教材教研改写流水线封装为 DeepSeek Harness 原生插件，无缝支持 Agent 工具调用与自动化编排。

### 核心特性
- **状态单一真相 (GraphState)**：基于 Pydantic 与幂等 Reducers 维护唯一可信状态；
- **8 项纯代码确定性门禁 (Deterministic Gates)**：
  - `source_gate` (G1): 原文切片与可信核验
  - `diagnosis_gate` (G2): 独立阅读痛点审计
  - `dependency_gate` (G3): Kahn 拓扑排序无环与依赖闭包完整性
  - `pedagogy_gate` (G4): 11 必备小节覆盖与“显然”跳步检测
  - `feedback_gate` (G5): 三级阶梯脚手架提示与任务完整性
  - `student_trial_gate` (G6): 多画像学生试读仿真与卡点雷达
  - `output_gate` (G7): LaTeX 公式守恒与定界符配平
  - `version_gate` (G8): 哈希后验一致性与版本签发
- **5 个独立业务子图 (Subgraphs)**：原文核验、阅读审计、依赖拓扑、正文撰写、阶梯任务。
- **SQLite 断点续跑 (SqliteSaver)**：支持任意阶段断点持久化与即时恢复。
- **最小可交付包 (Release Deliverables)**：全门禁通过后自动签发 8 大核心制品（含 SHA256 哈希清单）。

---

## 2. 导出工具 (Agent Tools)

### `langgraph_courseware_pipeline`
流水线核心驱动工具。
- `action`:
  - `run`: 启动流水线
  - `resume`: 从 SQLite 检查点恢复执行
  - `status`: 查询会话线程与检查点状态
  - `visualize`: 导出 LangGraph Mermaid 拓扑计算图
  - `test`: 运行全量单元测试与黄金路径
- `raw_files`: 原始教材文件列表（Markdown 或 PDF）
- `discipline`: 学科选择 (`math` / `physics`)，默认 `math`
- `output_dir`: 交付包目录（默认在输入文件所在目录下建立 `<string>_uncle` 子文件夹，其中 string 为输入文件名）
- `checkpoint_db`: SQLite 检查点文件（默认 `pipeline_state.db`）
- `thread_id`: 线程会话 ID（默认 `session_01`）
- `max_retry`: 门禁最大重试上限（默认 3）

### `langgraph_courseware_gate`
确定性门禁独立核验工具。
- `gate`: `all` | `source_gate` | `diagnosis_gate` | `dependency_gate` | `pedagogy_gate` | `feedback_gate` | `student_trial_gate` | `output_gate` | `version_gate`
- `state_file`: 状态 JSON 文件路径（可选）

---

## 3. 架构与运行环境

- **插件位置**: `~/.dsh/plugins/my_uncle_zhang`
- **运行时支持**: Node.js ESM + Python 3.10+ (已支持 langgraph, langchain_core, pydantic, pytest)
