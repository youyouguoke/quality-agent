---
name: root-cause-analysis
description: 根因推理链分析，从客退现象出发跨表关联追溯不良物料、供应商、批次，构建完整证据链定位根本原因
---

## 核心原则：假设-验证式推理

根因分析不是简单的统计排名。要用"提出假设→寻找证据→反向验证→排除或确认"的方法论：
- 初步结论必须经过至少一种对比验证才能输出
- 主动寻找反例（如果假设成立，那XX应该也有问题，实际有没有？）
- 区分"相关"和"因果"（该物料不良占比高，可能只是因为用量大）

## 执行流程

### 阶段1：现象识别与假设提出
1. 通过 MCP zhimi 获取客退概况，识别 TOP 不良原因和 TOP 不良物料
2. 对占比最高的不良，查询 return_data 获取相关 SN 列表
3. **提出初步假设**：基于统计结果提出1-2个可能的根因假设
   - 假设A：XX物料来自供应商YY，是供应商来料问题
   - 假设B：问题集中在ZZ工厂，可能是装配工艺问题

### 阶段2：正向追溯（收集支持证据）
4. 对典型 SN 查询 sn_quality_key_material 获取关键物料和供应商
5. 按不良物料的供应商统计关联 SN 数量
6. 对嫌疑供应商查询 supplier_quality_iqc 检查 IQC 数据
7. 查询 maintain_consume_material 确认维修实际更换了什么物料

### 阶段3：反向验证（对比推理，核心差异化步骤）
8. **跨SKU验证**：调用 `comparative_analysis(supplier_name=嫌疑供应商, compare_type="cross_sku")`
   - 如果该供应商在其他SKU上也有大量不良 → 支持"供应商系统性问题"假设
   - 如果其他SKU没问题 → 可能不是供应商问题，需考虑装配/设计因素
9. **跨供应商验证**：调用 `comparative_analysis(defect_material=不良物料, compare_type="cross_supplier")`
   - 如果同物料其他供应商也有不良 → 可能是物料规格/设计问题
   - 如果只有一家有问题 → 确认是该供应商的个体质量问题
10. **跨时间验证**：调用 `comparative_analysis(sku_name=SKU, compare_type="cross_time")`
    - 退货量突增 → 批次性问题（某个时间点引入的变更）
    - 退货量稳定 → 慢性问题（设计或工艺的固有缺陷）

### 阶段4：综合归因
11. 汇总正向证据和反向验证结果，给出根因判定
12. 读取 knowledge/质量基线标准.md 对比指标
13. 给出改善建议

## 领域知识

- 关联键：sn_no 贯穿 return_data → sn_quality_data → sn_quality_key_material → maintain_consume_material
- supplier_name 从 sn_quality_key_material 关联到 supplier_quality_iqc 和 supplier_performance_comparison
- material_code 从 sn_quality_key_material 关联到 supplier_performance_comparison 做同物料多供应商对比
- defect_material、defect_material_supplier、defect_cause 字段可能包含多个值（逗号分隔），需拆分后统计
- defect_material_batch 仅存在于 return_data 表，是追溯批次问题的关键字段
- maintain_consume_material 记录维修实际更换的物料，是确认根因的强信号
- 当单一不良原因占比超过 40% 时，存在集中性不良，应重点追溯

## 推理模式参考

| 假设 | 正向证据 | 反向验证方法 | 结论 |
|------|---------|-------------|------|
| 供应商A来料不良 | 不良物料指向供应商A | cross_sku：供应商A在其他SKU也有问题？ | 是→供应商通病；否→排除 |
| 物料X设计缺陷 | 物料X不良占比高 | cross_supplier：其他供应商的物料X也有问题？ | 是→设计问题；否→供应商个体问题 |
| 批次性问题 | 集中在某批次号 | cross_time：退货量是突增还是一直高？ | 突增→批次问题；稳定→慢性问题 |
| 工厂装配问题 | 不良集中在某工厂 | cross_sku：同工厂其他SKU也有类似不良？ | 是→工艺问题；否→该SKU设计问题 |

## 输出格式要求

### 一、问题概述
简述客退异常现象

### 二、不良集中度分析
展示 TOP 不良原因和 TOP 不良物料的占比

### 三、初步假设
列出1-2个根因假设及推理依据

### 四、正向追溯证据
物料追溯表格 + 供应商 IQC 数据 + 维修物料确认

### 五、反向验证结果
展示对比分析结果，逐个验证或排除假设：
- 跨SKU对比结果 → 支持/排除供应商假设
- 跨供应商对比结果 → 支持/排除物料设计假设
- 跨时间对比结果 → 判断突发/慢性

### 六、根因判定
用完整证据链输出，标注哪些假设被验证、哪些被排除：
```
初步假设：供应商A的XX物料有来料不良
正向证据：不良物料60%指向供应商A，IQC合格率仅92%
反向验证：供应商A在其他3个SKU上也有不良记录（跨SKU验证通过）
         同物料其他供应商无明显不良（跨供应商验证通过）
根因确认：供应商A的XX物料存在系统性来料不良
```

### 七、改善建议
紧急措施、短期措施、长期措施各1-2条
