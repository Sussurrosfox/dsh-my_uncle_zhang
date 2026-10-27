# -*- coding: utf-8 -*-
"""
lang.mock_content
-----------------
阶段 E.1 / E.3: 标准全量 Mock 课件内容与自测数据集。
提供真实的高中数学必修第一册《集合的概念》结构化实体、Task 任务模型与原始讲义。
"""

from __future__ import annotations
from typing import Any
from lang.state import Task, ConceptNode, LearningUnit, SourceNode

MOCK_SOURCE_SLICES = [
    SourceNode(
        source_id="src_1",
        source_file="math_set.md",
        page=1,
        source_quote="一般地，我们把研究对象统称为元素，把一些元素组成的总体叫做集合。简称集。",
        transcription="一般地，我们把研究对象统称为元素，把一些元素组成的总体叫做集合。简称集。",
        transcription_status="verified",
    ),
    SourceNode(
        source_id="src_2",
        source_file="math_set.md",
        page=2,
        source_quote="如果 a 是集合 A 的元素，就说 a 属于集合 A，记作 a ∈ A；如果 a 不是集合 A 的元素，就说 a 不属于集合 A，记作 a ∉ A。",
        transcription="如果 a 是集合 A 的元素，就说 a 属于集合 A，记作 a ∈ A；如果 a 不是集合 A 的元素，就说 a 不属于集合 A，记作 a ∉ A。",
        transcription_status="verified",
    ),
    SourceNode(
        source_id="src_3",
        source_file="math_set.md",
        page=3,
        source_quote="常用的数集有自然数集 N、正整数集 N* 或 N+、整数集 Z、有理数集 Q、实数集 R。不含任何元素的集合叫做空集，记作 ∅。",
        transcription="常用的数集有自然数集 N、正整数集 N* 或 N+、整数集 Z、有理数集 Q、实数集 R。不含任何元素的集合叫做空集，记作 ∅。",
        transcription_status="verified",
    ),
]

MOCK_NODES = [
    ConceptNode(
        node_id="node_1",
        kind="concept",
        statement="集合与元素概念",
        source_refs=["src_1"],
        observable_evidence="明确元素的确定性、互异性、无序性"
    ),
    ConceptNode(
        node_id="node_2",
        kind="concept",
        statement="元素与集合的从属关系",
        source_refs=["src_2"],
        observable_evidence="熟练掌握 ∈ 和 ∉ 的使用场景与单向关系"
    ),
    ConceptNode(
        node_id="node_3",
        kind="concept",
        statement="常用数集与空集符号",
        source_refs=["src_3"],
        observable_evidence="准确区分 N, Z, Q, R 与空集 ∅"
    ),
]

MOCK_UNITS = [
    LearningUnit(
        unit_id="unit_1",
        title="探究集合与元素的本原定义",
        objectives=["掌握集合的三个特征并能判断对象能否构成集合"],
        completion_criteria="正确辨析确定性、互异性并完成所有练习",
        node_refs=["node_1"],
    ),
    LearningUnit(
        unit_id="unit_2",
        title="元素与集合的属于符号及逻辑断言",
        objectives=["掌握属于与不属于符号的严谨用法"],
        completion_criteria="能运用 ∈ 与 ∉ 正确判断数或对象是否在特定集合中",
        node_refs=["node_2"],
    ),
    LearningUnit(
        unit_id="unit_3",
        title="特定常用数集与空集的边界规约",
        objectives=["掌握常见数集记号与空集的定义和独特性质"],
        completion_criteria="正确识别数集符号与空集，避免把空集与单元素集混淆",
        node_refs=["node_3"],
    ),
]

MOCK_TASKS = [
    # Unit 1 Tasks (node_1)
    Task(
        task_id="task_1",
        unit_id="unit_1",
        node_id="node_1",
        objective="考查集合中元素的确定性判断",
        task_type="即时核验",
        prompt="下列各项中，不能组成集合的是哪些项？并说明理由：(A) 2026年参加高考的所有高中生；(B) 高一数学课本中所有的难题；(C) 平面上到原点距离等于 1 的所有点。",
        expected_evidence="指出选项B中的判定标准不具有客观唯一尺度",
        hint_1="回忆集合中元素的确定性特征。",
        hint_2="检查每个命题中用于筛选对象的标准是否具有客观明确的评判尺度。",
        hint_3="对比选项B中的难题与选项A和C中具有客观严格判定准则的表述细节。",
        answer="选项 (B) 不能组成集合。因为'难题'没有明确客观的衡量标准，不满足集合中元素的确定性。",
        worked_solution="完整解析：选项 (B) 不能组成集合。因为'难题'没有明确客观的衡量标准，不满足集合中元素的确定性。",
        common_errors=["认为 (C) 不是集合，误以为几何轨迹不是集合"],
        error_reasons=["混淆了代数数集与几何图形点集的本质区别，忽略了确定性原则"],
        retry_prompt="判断下列对象能否构成集合：'所有的好学生'。",
        retry_task="判断下列对象能否构成集合：'所有的好学生'。",
        retry_answer="不能构成集合，因为'好学生'的标准不确定。",
        boundary_note="集合中元素的三个基本特性为：确定性、互异性、无序性。",
        source_refs=["src_1"]
    ),
    Task(
        task_id="task_2",
        unit_id="unit_1",
        node_id="node_1",
        objective="考查集合元素的互异性约束",
        task_type="变式",
        prompt="已知由实数 $a$ 和 $a^2$ 组成的集合中含有 2 个元素，求实数 $a$ 必须满足的条件。",
        expected_evidence="列出 a 不等于 a^2 的不等式并求解",
        hint_1="注意集合中元素的互异性要求。",
        hint_2="集合中含有 2 个元素，说明这两个元素在数值上彼此互不相等。",
        hint_3="令 a 与 a^2 不相等，解方程 a^2 - a = 0 从而准确找到必须排除的实数根。",
        answer="由互异性可知 a != 0 且 a != 1",
        worked_solution="完整推导：由互异性可知 a != 0 且 a != 1，因为若 a 等于 0 或 1 则元素重复。",
        common_errors=["忽略互异性要求，得出 a 为任意实数"],
        error_reasons=["对集合元素互异性的约束条件缺乏前置防御意识"],
        retry_prompt="已知由实数 x 和 |x| 组成集合 S，若 S 中只有一个元素，求实数 x 的范围。",
        retry_task="已知由实数 x 和 |x| 组成集合 S，若 S 中只有一个元素，求实数 x 的范围。",
        retry_answer="由互异性若只有一个元素，则必有 x = |x|，解得 x >= 0。",
        boundary_note="求出待定字母后，必须带回原集合检验互异性是否成立。",
        source_refs=["src_1"]
    ),
    Task(
        task_id="task_3",
        unit_id="unit_1",
        node_id="node_1",
        objective="考查集合互异性在计算机哈希表去重中的跨学科迁移",
        task_type="迁移",
        prompt="计算机科学中的哈希表 HashSet 要求键值不可重复，请结合集合的数学定义分析其底层对应关系。",
        expected_evidence="论述哈希去重与数学集合互异性的语义一致性",
        hint_1="联想集合的互异性特征在数据结构中的应用。",
        hint_2="当向集合容器中插入已存在的重复元素时，其元素总容量保持恒定不变。",
        hint_3="分析哈希冲突校验机制与数学公理体系中元素互不相同原则的精确语义映射关系。",
        answer="哈希集合通过键值唯一性保证了数学集合的互异性，重复元素无法重复存入。",
        worked_solution="深度解析：哈希集合通过键值唯一性保证了数学集合的互异性，重复元素无法重复存入。这体现了数学抽象在工业软件架构中的直接落地。",
        common_errors=["误认为哈希表存储有固定顺序"],
        error_reasons=["混淆了有序序列与无序集合的数学与工程定义"],
        retry_prompt="Python 中的 set([1, 1, 2]) 输出结果长度是多少？对应哪条数学性质？",
        retry_task="Python 中的 set([1, 1, 2]) 输出结果长度是多少？对应哪条数学性质？",
        retry_answer="长度为 2，对应互异性。",
        boundary_note="在跨学科迁移中，数学的无序性与互异性是现代集合数据结构的理论基石。",
        source_refs=["src_1"]
    ),

    # Unit 2 Tasks (node_2)
    Task(
        task_id="task_4",
        unit_id="unit_2",
        node_id="node_2",
        objective="考查属于与不属于符号在常见数集中的应用",
        task_type="即时核验",
        prompt="用符号属于或不属于判断：0 是否属于自然数集 N？",
        expected_evidence="写出 0 属于 N 的符号表述",
        hint_1="回忆自然数集 N 的现代规范定义范围。",
        hint_2="在现行高中数学教材中，自然数集包含所有非负整数。",
        hint_3="核实关键非负整数：0 是最小的自然数，因此属于自然数集。",
        answer="0 属于自然数集 N",
        worked_solution="规范作答：0 是非负整数，所以 0 属于自然数集 N，记作 0 in N。",
        common_errors=["误以为 0 不是自然数"],
        error_reasons=["未牢记现代教材规定 0 是自然数集 N 的元素"],
        retry_prompt="0 是否属于正整数集 N*？",
        retry_task="0 是否属于正整数集 N*？",
        retry_answer="0 不属于正整数集 N*。",
        boundary_note="符号 in 和 not in 仅能用于表示元素与集合之间的从属关系。",
        source_refs=["src_2"]
    ),
    Task(
        task_id="task_5",
        unit_id="unit_2",
        node_id="node_2",
        objective="考查方程解集元素的确定与属于判断",
        task_type="变式",
        prompt="设集合 A 为方程 x^2 - 2x - 3 = 0 的所有实数根构成的集合，求集合 A 的全部元素。",
        expected_evidence="因式分解得到两个根 3 和 -1",
        hint_1="解出该一元二次方程的所有实数根。",
        hint_2="利用因式分解法将二次方程分解为 (x-3)(x+1) = 0。",
        hint_3="方程的两个实数解分别对应集合中的离散元素，注意用逗号分隔两个根。",
        answer="{3, -1}",
        worked_solution="求解过程：由 (x-3)(x+1) = 0 得根为 3 和 -1，故集合为 {3, -1}。",
        common_errors=["只写一个根，遗漏负根"],
        error_reasons=["解方程不完整或运算疏忽"],
        retry_prompt="设集合 B 为方程 x^2 = 4 的根构成的集合，求集合 B。",
        retry_task="设集合 B 为方程 x^2 = 4 的根构成的集合，求集合 B。",
        retry_answer="{2, -2}",
        boundary_note="描述法集合中，元素必须且只需满足所给谓词条件。",
        source_refs=["src_2"]
    ),
    Task(
        task_id="task_6",
        unit_id="unit_2",
        node_id="node_2",
        objective="考查数据库 IN 操作符与属于关系的映射迁移",
        task_type="迁移",
        prompt="在 SQL 中语句 WHERE id IN (1, 2) 等价于数学上的什么属于断言？",
        expected_evidence="写出 id 属于集合 {1, 2} 的数学表达式",
        hint_1="将圆括号内的常量列表抽象为一个离散集合。",
        hint_2="将字段 id 视为变量元素，判断其是否属于该常量列表构成的集合。",
        hint_3="SQL 中的 IN 关键字正是谓词逻辑中元素属于符号的直接对应表示方式。",
        answer="等价于 id 属于集合 {1, 2}",
        worked_solution="理论解析：SQL 的 IN 谓词等价于 id 属于集合 {1, 2}，即 id in {1, 2}。",
        common_errors=["误认为 IN 是逻辑与 AND 关系"],
        error_reasons=["混淆了集合归属判定中的析取语义与合取语义"],
        retry_prompt="SQL 中 NOT IN (1, 2) 对应数学中的什么符号？",
        retry_task="SQL 中 NOT IN (1, 2) 对应数学中的什么符号？",
        retry_answer="对应不属于符号 not in。",
        boundary_note="关系数据库理论完全建立在经典集合论的谓词演算基础之上。",
        source_refs=["src_2"]
    ),

    # Unit 3 Tasks (node_3)
    Task(
        task_id="task_7",
        unit_id="unit_3",
        node_id="node_3",
        objective="考查空集与单元素零集的本质区别",
        task_type="即时核验",
        prompt="集合 {0} 与空集是同一个集合吗？请说明理由。",
        expected_evidence="比较两者的元素个数，说明 0 是元素而空集无元素",
        hint_1="复习空集的严格定义：不含任何元素的集合。",
        hint_2="集合 {0} 中包含一个确定的元素即数字 0，计算其元素个数。",
        hint_3="对比元素个数：空集的基数为 0，而集合 {0} 的基数为 1，二者并不相等。",
        answer="不是同一个集合，因为 {0} 含有元素 0 而空集不含任何元素。",
        worked_solution="辨析说明：不是同一个集合，因为 {0} 含有元素 0 而空集不含任何元素。两者基数不同。",
        common_errors=["认为 0 代表什么都没有，所以两者相同"],
        error_reasons=["混淆了数值为0的元素与不含元素的集合的概念区别"],
        retry_prompt="判断：集合 {空集} 是空集吗？",
        retry_task="判断：集合 {空集} 是空集吗？",
        retry_answer="不是空集，它是包含一个元素的单元素集。",
        boundary_note="空集是唯一不含任何元素的集合，书写时绝不能在花括号中嵌套空集符号。",
        source_refs=["src_3"]
    ),
    Task(
        task_id="task_8",
        unit_id="unit_3",
        node_id="node_3",
        objective="考查方程解集为空集的参数分类讨论",
        task_type="变式",
        prompt="若方程 ax = 1 在实数范围内的解集为空集，求实数 a 的值。",
        expected_evidence="分类讨论 a=0 时无解，a!=0 时有解",
        hint_1="若解集为空集，说明该方程在实数范围内完全无解。",
        hint_2="分析一元一次方程当未知数系数为 0 时方程解的具体情况。",
        hint_3="当 a 等于 0 时方程化为 0 乘 x 等于 1 无解；当 a 不为 0 时有唯一解。",
        answer="a = 0",
        worked_solution="推导论证：当 a = 0 时，0x = 1 无解，解集为空集；当 a != 0 时，x = 1/a，解集非空。所以 a = 0。",
        common_errors=["忽略讨论 a=0 的边界情况，直接作除法"],
        error_reasons=["缺乏最高次项系数含参数时的分类讨论意识"],
        retry_prompt="已知集合 B = {x in R | x^2 + 1 = 0}，求集合 B。",
        retry_task="已知集合 B = {x in R | x^2 + 1 = 0}，求集合 B。",
        retry_answer="因为无实根，所以集合 B 为空集。",
        boundary_note="涉及参数方程解集为空集的问题，务必优先分类讨论系数为 0 的情况。",
        source_refs=["src_3"]
    ),
    Task(
        task_id="task_9",
        unit_id="unit_3",
        node_id="node_3",
        objective="考查编程语言中空集合对象与空指针 None 的本质区别",
        task_type="迁移",
        prompt="在 Python 中空集合 set() 与 None 有何本质区别？请从空集定义阐明。",
        expected_evidence="指出空集合是合法容器对象而 None 是空引用",
        hint_1="将集合比作容器：空集合是一个空盒子，而 None 是没有盒子。",
        hint_2="空集合是一个具体的合法对象，其长度为 0；None 表示变量未绑定有效实体。",
        hint_3="空集合支持集合运算与从属判定返回假，而对 None 调用集合方法会抛出异常错误。",
        answer="set() 是长度为 0 的合法集合容器，而 None 表示空引用对象。",
        worked_solution="概念辨析：set() 是长度为 0 的合法集合容器，而 None 表示空引用对象。在集合论中空集是确定存在的集合实体。",
        common_errors=["把空集合对象与空指针概念混为一谈"],
        error_reasons=["对引用的存在性与实体内部状态的空状态缺乏清晰抽象"],
        retry_prompt="len(set()) 的返回值是多少？",
        retry_task="len(set()) 的返回值是多少？",
        retry_answer="返回值是 0。",
        boundary_note="空集是一个合法对象，对空集的任何属于断言均产生确定性的布尔假值。",
        source_refs=["src_3"]
    ),
]

MOCK_GOOD_MD = """# 集合的概念与表示

## 一、集合与元素的概念

在日常生活和数学研究中，我们经常需要把某些特定的对象放在一起进行研究。
一般地，我们把研究对象统称为**元素**（element），把一些元素组成的总体叫做**集合**（set），简称为集。

集合中的元素具有三个基本特征：
1. **确定性**：给定一个集合，任何一个对象是不是这个集合的元素是明确的。
2. **互异性**：集合中的元素是互不相同的，相同的元素只能算作一个。
3. **无序性**：集合中的元素没有先后次序之分。

{{task:task_1}}

{{task:task_2}}

### 计算机与集合论拓展：去重与哈希
集合的互异性在现代计算机科学中有极深的应用。

{{task:task_3}}

<details><summary>点击查看任务3迁移解析</summary>
计算机工程中的哈希集合与数学集合性质高度统一。
</details>

## 二、元素与集合的关系

如果 $a$ 是集合 $A$ 的元素，我们就说 $a$ **属于**集合 $A$，记作 $a \\in A$；
如果 $a$ 不是集合 $A$ 的元素，我们就说 $a$ **不属于**集合 $A$，记作 $a \\notin A$。

{{task:task_4}}

{{task:task_5}}

### 关系数据库与集合从属关系迁移
在实际系统设计中，查询条件与元素从属判定息息相关。

{{task:task_6}}

<details><summary>点击查看任务6迁移解析</summary>
SQL IN 语句本质上即为数学元素从属关系的真假断言。
</details>

## 三、常用数集与空集

在数学中，有一些特别常用的数集，我们用特定的字母记号来表示：
- 自然数集（非负整数集）：$\\mathbf{N}$
- 正整数集：$\\mathbf{N}^*$ 或 $\\mathbf{N}^+$
- 整数集：$\\mathbf{Z}$
- 有理数集：$\\mathbf{Q}$
- 实数集：$\\mathbf{R}$

此外，还有一个特殊的集合，它不含任何元素。我们把**不含任何元素的集合叫做空集**，记作 $\\emptyset$。

{{task:task_7}}

{{task:task_8}}

### 计算机科学中空集合与空引用的边界迁移
空集的存在性保证了交集运算等代数结构的封闭性。

{{task:task_9}}

<details><summary>点击查看任务9迁移解析</summary>
空集是实体容器对象，长度为0；空引用是不指向任何容器的指针。
</details>
"""


def get_mock_state_kwargs() -> dict[str, Any]:
    """返回用于组装完整合规初始 GraphState 的字典参数"""
    return {
        "build_id": "mock_build_001",
        "raw_files": ["math_set.md"],
        "sources": MOCK_SOURCE_SLICES,
        "nodes": MOCK_NODES,
        "units": MOCK_UNITS,
        "tasks": MOCK_TASKS,
        "good_md": MOCK_GOOD_MD,
        "good_md_path": "math_set_good.md",
        "gate_results": [],
        "fix_history": [],
        "reading_obstacles": [],
        "student_trials": [],
        "manifest": None,
        "retry_counts": {},
        "stop_flag": None,
    }
