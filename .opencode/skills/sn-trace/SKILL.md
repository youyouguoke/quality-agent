---
name: sn-trace
description: SN全链路溯源，通过SN序列号查询产品的生产、出货、客退全链路质量数据和关键物料信息
---

## 执行流程

1. 在 return_data 表（通过 MCP zhimi `get_return_data` 或本地数据库）中查询该 SN 的客退记录
2. 在 sn_quality_data 表中查询该 SN 的生产/出货质量数据
3. 在 sn_quality_key_material 表中查询该 SN 使用的关键物料
4. 在 maintain_consume_material 表中查询维修更换的物料
5. 综合以上数据给出问题定位

## 领域知识

- SN 是产品的唯一序列号标识，贯穿生产到售后全流程
- sn_quality_data 表包含：SN、SKU名称、代工厂、生产日期、制程直通率、出货日期、退货时间、受理原因、复测结果、不良原因、不良物料、不良物料供应商、责任归属等30个字段
- sn_quality_key_material 表包含：SN、物料编码、物料名称、批次合格率、供应商、采购订单号
- maintain_consume_material 表包含：SN、维修物料编码、物料名称、消耗数量
- 如果多个 SN 使用了同一批次物料且都出现问题，可能是物料批次问题
- 关联键：sn_no 贯穿 return_data、sn_quality_data、sn_quality_key_material、maintain_consume_material 四张表

## 输出格式要求

### SN基本信息
展示 SN 的产品名称、生产工厂、生产日期等基本信息

### 质量数据
展示该 SN 的客退/不良记录

### 关键物料
用表格展示该 SN 使用的关键物料清单

### 维修记录
展示维修更换的物料

### 分析结论
综合以上信息给出该 SN 的问题定位和建议
