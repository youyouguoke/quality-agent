---
name: factory-analysis
description: 代工厂质量分析，查询工厂的整体质量数据和月度趋势
---

## 执行流程

1. 在 return_data 表中按 production_factory 过滤查询该工厂的客退数据
2. 统计各不良原因、不良物料的分布
3. 读取 knowledge/质量基线标准.md 进行基线对比
4. 给出综合评价

## 领域知识

- 代工厂质量涵盖 PQC（制程检验）和 OQC（出货检验）等环节
- 关键指标：直通率、不良率、退货率
- 代工厂字段在不同表中命名不同：sn_quality_data 中叫 foundry，return_data 中叫 production_factory，supplier_quality_iqc 中叫 factory_name
- 不同工厂生产同一 SKU 时，可通过对比发现工厂端的质量差异

## 输出格式要求

### 工厂基本情况
展示工厂名称及关键质量指标

### 退货分析
展示该工厂生产产品的退货分布

### 基线对比
与基线对比标注等级

### 综合评价与建议
给出评价和改善建议
