---
name: root-cause-analysis
description: 根因推理链分析，从客退现象出发跨表关联追溯不良物料、供应商、批次，构建完整证据链定位根本原因
---

## 执行流程

1. **现象识别**：通过 MCP zhimi 获取客退概况，识别 TOP 不良原因和 TOP 不良物料
2. **聚焦异常**：对占比最高的不良原因/物料，查询 return_data 获取相关 SN 列表（含 defect_material_batch、defect_material_supplier 等字段）
3. **SN级追溯**：对典型 SN 查询 sn_quality_key_material 获取该 SN 使用的关键物料和供应商信息
4. **物料批次关联**：按不良物料的供应商统计关联 SN 数量，识别集中度
5. **供应商验证**：对嫌疑供应商查询 supplier_quality_iqc 检查其 IQC 质量数据和月度趋势
6. **维修物料确认**：查询 maintain_consume_material 确认维修实际更换了什么物料
7. **基线对比**：读取 knowledge/质量基线标准.md 对比供应商指标
8. **综合归因**：汇总证据链，给出根因判定和改善建议

## 领域知识

- 根因分析的核心是找共性：多个退货 SN 是否指向同一物料、同一供应商、同一批次
- 关联键：sn_no 贯穿 return_data → sn_quality_data → sn_quality_key_material → maintain_consume_material
- supplier_name 从 sn_quality_key_material 关联到 supplier_quality_iqc 和 supplier_performance_comparison
- material_code 从 sn_quality_key_material 关联到 supplier_performance_comparison 做同物料多供应商对比
- defect_material、defect_material_supplier、defect_cause 字段可能包含多个值（逗号分隔），需拆分后统计
- defect_material_batch 仅存在于 return_data 表，是追溯批次问题的关键字段
- maintain_consume_material 记录维修实际更换的物料，是确认根因的强信号
- 当单一不良原因占比超过 40% 时，存在集中性不良，应重点追溯
- 当多个 SN 的不良物料指向同一供应商时，大概率是供应商来料问题

## 输出格式要求

### 一、问题概述
简述客退异常现象

### 二、不良集中度分析
展示 TOP 不良原因和 TOP 不良物料的占比，标注是否超过预警阈值

### 三、物料追溯
用表格展示：不良物料 → 供应商 → 涉及 SN 数量 → 批次号

### 四、供应商质量验证
展示嫌疑供应商的 IQC 数据，与基线对比标注等级

### 五、维修确认
展示维修实际更换的物料统计

### 六、根因判定
用证据链形式输出：退货现象 → 不良集中 → 追溯到供应商 → IQC 数据验证 → 根因结论

### 七、改善建议
紧急措施、短期措施、长期措施各1-2条
