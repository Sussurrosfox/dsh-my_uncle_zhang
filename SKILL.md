---
name: my_uncle_zhang
description: my_uncle_zhang — LangGraph 自动化自学教材教研流水线插件。将 Markdown/PDF 课本转化为基于 LangGraph 状态机、8 项纯代码确定性门禁拦截、单一真相图状态 (GraphState) 与 5 独立子图驱动的自学教材教研体系。支持断点恢复与最小可交付包导出校验。
---

# LangGraph 自动化自学教材教研流水线技能规范

本插件将 Markdown/PDF 原材料教研改写流程转化为由 **LangGraph** 状态机驱动、严格由**确定性门禁 (Deterministic Gates)** 拓扑拦截、**状态单一真相 (GraphState)** 与**声明式 Agent 注册表**驱动的工业级流水线系统。

---

## 1. 核心工具说明

### 1.1 `langgraph_courseware_pipeline`
流水线核心驱动工具，负责控制流水线生命周期：
- `action="run"`: 启动流水线。必须传入 `raw_files`（原材料文件列表）。
- `action="resume"`: 从断点恢复流水线。
- `action="status"`: 查询 SQLite 数据库中的检查点历史与当前执行状态。
- `action="visualize"`: 获取主图的 Mermaid 计算图拓扑。
- `action="test"`: 运行测试套件与黄金路径验证。

### 1.2 `langgraph_courseware_gate`
确定性门禁独立核验工具，用于在阶段收官或终审前独立运行代码级质量核验：
- 8 大核心门禁：
  1. `source_gate`: 原文切片与可信核验
  2. `diagnosis_gate`: 独立阅读审计与痛点依据
  3. `dependency_gate`: 概念网络 Kahn 拓扑排序无环与闭包
  4. `pedagogy_gate`: 11 必备小节覆盖与禁“显然”跳步词
  5. `feedback_gate`: 三级阶梯脚手架提示与任务完整性
  6. `student_trial_gate`: 3 画像学生试读仿真与无停滞
  7. `output_gate`: 正文非空与 LaTeX 公式守恒配平
  8. `version_gate`: 全量哈希后验一致性与版本签发

---

## 2. 协作者规范与红线要求

1. **门禁唯一裁决权**：
   门禁为纯 Python 代码实现，拥有唯一裁决权。失败时必须按门禁反馈定向排查或回流修复，严禁在未通过门禁时强制签发交付包。
2. **状态单一真相**：
   所有业务对象严格统一在 `GraphState` 中流转，通过幂等 Reducer 合并。
3. **交付包原子性**：
   未全部通过门禁时，流水线触发熔断保护，拒绝向交付目录写入任何未签发半成品。
