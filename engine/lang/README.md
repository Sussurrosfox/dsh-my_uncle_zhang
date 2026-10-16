# LangGraph 自动化自学教材教研流水线 (LangGraph Courseware Pipeline)

本项目严格基于 `to_lang.md` 与 `to_upgrade.md` 规范实现，将基于 Markdown/PDF 课本的自学教材教研改写流程，转化为由 **LangGraph** 状态机驱动、严格由**确定性门禁 (Deterministic Gates)** 拓扑拦截、**状态单一真相 (GraphState)** 与**声明式 Agent 注册表**驱动的工业级流水线系统。

---

## 1. 核心架构与三大设计支柱

根据 `to_lang.md §1`，本流水线彻底摒弃了“把业务规则写进 LLM prompt 里祈祷它遵守”的脆弱模式，严格遵循三大工程支柱：

```
                    ┌───────────────────────────┐
                    │  GraphState (单一真相)     │
                    │  Pydantic + 自定义 Reducers│
                    └─────────────┬─────────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
┌──────────────────┐                             ┌───────────────────┐
│ 拓扑门禁 (Gates)  │                             │ 声明式 Agent 注册  │
│ 纯代码断言 + 熔断 │                             │ 白名单读写 + 确定性│
└──────────────────┘                             └───────────────────┘
```

1. **状态作为唯一真相（State as Single Truth）**：
   - 所有的业务对象（`SourceNode`, `ConceptNode`, `DependencyEdge`, `LearningUnit`, `Task`, `DiagnosisRecord`, `ReviewRecord`, `GateResult`, `ReleaseManifest`）都定义在统一的 `GraphState` 中；
   - 关键集合字段采用自定义 Reducer（`merge_by_key`, `merge_edges`, `merge_retry_counts`）进行幂等合并，天然支持断点恢复、增量重算与并发安全。
2. **门禁作为图的拓扑，而非 Prompt 规则（Gates as Topology）**：
   - 每个关键阶段后强制挂载门禁节点（Gate Node）；
   - 检查规则由**纯 Python 代码**实现（如 Kahn 算法拓扑排序判环、闭包完整性、11 必备小节覆盖、禁止“显然”跳步词、公式配平校验等），门禁拥有唯一裁决权；
   - 失败时自动按路由表定向回流到专职修复 Agent（如 `evidence_fixer`, `structure_rebuilder`），单门禁重试超 3 次触发熔断保护（`stop_and_report`）。
3. **Agent 与编排解耦（Declarative Agents）**：
   - Agent 定义在 YAML 注册表（`lang/config/agents.yaml`）中，声明其 `reads` 与 `writes` 字段白名单及绑定工具；
   - 节点工厂（`lang/node_factory.py`）对 Agent 输出执行严格白名单守卫，拦截一切越权写操作。

---

## 2. 目录结构与模块说明

```
lang/
├── config/
│   ├── agents.yaml               # 10 个角色 + 2 个修复 Agent 的声明式配置与白名单
│   ├── gates.yaml                # 8 个门禁的判定规则、重试上限 (3) 与错误路由表
│   └── disciplines/
│       ├── math.yaml             # 数学学科提示词补丁与边界规则
│       └── physics.yaml          # 物理学科提示词补丁与边界规则
├── prompts/                      # 12 个角色与修复 Agent 的专用提示词
│   ├── evidence_builder.md       # 原文证据提取
│   ├── source_verifier.md        # 证据核验与跨模态审查
│   ├── reading_auditor.md        # 独立阅读审计
│   ├── structure_rebuilder.md    # 概念网络与拓扑依赖重构
│   ├── unit_designer.md          # 学习单元规划
│   ├── writer.md                 # 11 要素正文撰写
│   ├── task_author.md            # 三层分级任务与分层脚手架编写
│   ├── student_simulator.md      # 多画像学生仿真试读
│   ├── arbiter.md                # 仿真仲裁
│   ├── evidence_fixer.md         # 证据修复专员
│   ├── converter_fixer.md        # 格式与数学公式修复专员
│   └── rubrics/
│       └── pedagogy_rubric.md    # 教学法评分量表
├── gates/
│   ├── base.py                   # 门禁抽象基类与评估调度
│   ├── deterministic.py          # 23 个纯 Python 确定性检查器
│   └── registry.py               # 门禁实例化与注册中心
├── subgraphs/                    # 5 个独立业务子图
│   ├── sg1_source.py             # 子图 1: 原文切片与可信核验 (evidence_builder -> source_verifier)
│   ├── sg2_diagnosis.py          # 子图 2: 独立阅读审计 (reading_auditor)
│   ├── sg3_structure.py          # 子图 3: 概念依赖网重构 (structure_rebuilder)
│   ├── sg4_pedagogy.py           # 子图 4: 单元规划与正文撰写 (unit_designer -> writer)
│   └── sg5_feedback.py           # 子图 5: 阶梯任务设计 (task_author)
├── tests/                        # 完整测试套件
│   ├── test_state_and_reducers.py# 状态模型与 Reducer 幂等单测
│   ├── test_deterministic_gates.py# 8 门禁核心代码规则确定性断言
│   ├── test_subgraphs.py         # 5 个子图独立执行测试
│   └── test_e2e_pipeline.py      # 端到端黄金路径、P0 熔断与交付校验测试
├── node_factory.py               # Agent 与 Gate 节点工厂、写白名单校验器
├── graph_builder.py              # 主图装配、全局错误回流、级联失效标记与发布签发
├── exporters.py                  # 最小可交付包落盘与 SHA256 强校验
├── pipeline.py                   # 管道启动器、SqliteSaver 断点续跑与 CLI 入口
└── state.py                      # 业务实体定义与 GraphState 模型
```

---

## 3. 门禁系统 (The 8 Gates)

流水线中的 8 个核心门禁按顺序严格把关：

| 门禁代号 | 门禁名称 | 触发时机 | 核心检查项 | 严重级别与处理 |
|---|---|---|---|---|
| **Gate 1** | `source_gate` | SG1 完成后 | 所有切片核验、高风险 100% 复核、风险行动闭环 | P1 路由至 `evidence_fixer` |
| **Gate 2** | `diagnosis_gate` | SG2 完成后 | 诊断非空、阅读痛点证据有效、禁模糊词 (不够好/不清晰) | P1 路由至 `reading_auditor` |
| **Gate 3** | `dependency_gate` | SG3 完成后 | **Kahn 算法拓扑排序无环**、前置闭包无悬空依赖 | **P0_stop** 熔断，或回流 `structure_rebuilder` |
| **Gate 4** | `pedagogy_gate` | SG4 完成后 | 11 必需小节覆盖、可观察动词目标、**禁止“显然/容易证明”跳步** | P1 路由至 `writer` |
| **Gate 5** | `feedback_gate` | SG5 完成后 | 必填字段齐全、**三级脚手架提示完整**、预期反应有效 | P1 路由至 `task_author` |
| **Gate 6** | `student_trial_gate`| 学生仿真后 | 3 画像仿真覆盖率、无停滞卡点、仲裁通过 | P1 路由至 `writer` |
| **Gate 7** | `output_gate` | 终审阶段 | 正文非空、LaTeX 公式 `$` / `$$` 守恒配平 | P1 路由至 `converter_fixer` |
| **Gate 8** | `version_gate` | 发布前 | 前 7 个门禁全通过、哈希后验一致性、题库导出对齐 | P0 阻断发布 |

---

## 4. 最小可交付包 (Release Deliverables)

流水线成功通过全部门禁后，由 `lang/exporters.py` 机械化写出以下核心交付制品，若未通过门禁或被熔断，系统**绝不向交付目录写入任何半成品**：

1. `good.md`：重构后的完整教材/学案 Markdown 正文；
2. `graph.json`：概念依赖图拓扑数据（节点与有向依赖边）；
3. `tasks.json`：伴随式的三层分级题库与脚手架提示；
4. `evidence_manifest.json`：原文图谱与核验审计证据清单；
5. `diagnosis_report.md`：阅读痛点审计报告；
6. `trial_report.md`：多画像学生试读仿真与卡点雷达报告；
7. `gate_reports/*.json`：全量 8 个门禁的判定结果与证据链归档；
8. `release_manifest.json`：发布清单（含所有输入/输出文件的 SHA256 哈希值、版本号、工具版本与门禁签名）。

---

## 5. 快速上手

### 5.1 运行全量自动化测试
系统内置了完备的测试套件，执行：
```bash
python -m pytest lang/tests/ -v
```
输出：`18 passed`。

### 5.2 命令行启动流水线
支持单输入文件或多输入文件、断点恢复与多学科配置：
```bash
python main.py --input 01_第一章_集合与常用逻辑用语.md --discipline math --output release_deliverables
```

参数说明：
- `--input`：原始课本/讲义文件路径（可传入多个）；
- `--discipline`：学科配置，可选 `math`（默认）或 `physics`；
- `--output`：交付制品输出目录（默认 `deliverables`）；
- `--db`：Sqlite 检查点数据库路径（默认 `pipeline_state.db`）；
- `--thread`：会话线程 ID（默认 `session_01`）；
- `--resume`：断点恢复模式（默认 `False`）。

### 5.3 Python 代码中调用
```python
from lang.pipeline import run_pipeline

result = run_pipeline(
    raw_files=["01_第一章_集合与常用逻辑用语.md"],
    discipline="math",
    output_dir="my_deliverables",
    checkpoint_db="pipeline.db",
    thread_id="session_math_01"
)

if result["success"]:
    print("交付成功，清单:", result["manifest"])
else:
    print("流水线拦截，原因:", result["stop_flag"])
```
