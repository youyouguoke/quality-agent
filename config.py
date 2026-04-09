"""
质量管理 AI Agent 系统 - 配置文件
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ======================== MySQL 数据库配置 ========================
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "quality_db"),
    "charset": "utf8mb4",
    "pool_size": int(os.getenv("DB_POOL_SIZE", 5)),
    "pool_name": "quality_pool",
}

# ======================== LLM 配置 ========================
LLM_CONFIG = {
    "model": os.getenv("LLM_MODEL", "deepseek-chat"),
    "api_key": os.getenv("LLM_API_KEY", ""),
    "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", 0.1)),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", 4096)),
}

# ======================== API 服务配置 ========================
API_CONFIG = {
    "host": os.getenv("API_HOST", "0.0.0.0"),
    "port": int(os.getenv("API_PORT", 8000)),
    "debug": os.getenv("API_DEBUG", "false").lower() == "true",
}

# ======================== MCP 配置 ========================
MCP_CONFIG = {
    "url": os.getenv("MCP_URL", "https://dm.zhimi.com/mcp"),
    "auth_token": os.getenv("MCP_AUTH_TOKEN", "642E94F7-AC16-4565-ABA7-A8F7F80099A8"),
    "user": os.getenv("MCP_USER", "zhangzhiguang3"),
    "timeout": int(os.getenv("MCP_TIMEOUT", 60)),
}

# ======================== 预警监控配置 ========================
ALERT_CONFIG = {
    # 巡检间隔（秒），默认 4 小时
    "check_interval": int(os.getenv("ALERT_INTERVAL", 14400)),
    # 是否启用定时巡检
    "enabled": os.getenv("ALERT_ENABLED", "true").lower() == "true",
    # 告警记录最大保留条数
    "max_alerts": int(os.getenv("ALERT_MAX_RECORDS", 500)),
    # Webhook 通知地址（可选，为空则不推送）
    "webhook_url": os.getenv("ALERT_WEBHOOK_URL", ""),
}

# ======================== 质量数据表映射 ========================
# 现有 MySQL 数据库中的质量数据资产表名
TABLE_NAMES = {
    # 7.1 SN全链路质量数据
    "sn_quality_data": "sn_quality_data",
    "sn_quality_key_material": "sn_quality_key_material",
    # 7.2 供应商质量数据
    "supplier_quality_iqc": "supplier_quality_iqc",
    "supplier_quality_iqc_monthly": "supplier_quality_iqc_monthly",
    "supplier_performance_comparison": "supplier_performance_comparison",
    # 7.3 SKU质量数据
    "sku_quality": "SKU_Quality",
    "sku_quality_monthly": "SKU_Quality_Monthly",
    # 7.4 代工厂质量数据
    "factory_quality": "Factory_Quality",
    "factory_quality_monthly": "Factory_Quality_Monthly",
    # 7.5 物料质量数据
    "part_quality": "Part_Quality",
    "part_quality_monthly": "Part_Quality_Monthly",
    # 7.6 IQC NG记录
    "iqc_ng": "IQC_NG",
    # 7.7 PQC NG记录
    "pqc_ng": "PQC_NG",
    # 7.8 OQC NG记录
    "oqc_ng": "OQC_NG",
    # 7.9 客退数据
    "return_data": "return_data",
    "maintain_consume_material": "maintain_consume_material",
}

# 当前数据库中尚未创建的表（保留配置，查询时返回友好提示）
UNAVAILABLE_TABLES = {
    "sku_quality", "sku_quality_monthly",
    "factory_quality", "factory_quality_monthly",
    "part_quality", "part_quality_monthly",
    "iqc_ng", "pqc_ng", "oqc_ng",
}

# ======================== 数据表字段定义 ========================
# 用于Agent理解数据结构，以及构建安全的SQL查询
# columns: 数据库中的实际英文列名（用于SQL查询和白名单校验）
# column_mapping: 英文列名 -> 中文含义（供Agent理解字段语义）
TABLE_SCHEMAS = {
    "sn_quality_data": {
        "description": "SN的生产、出货和客退质量数据（仅同步有客退数据的SN）",
        "source": "成品质量追踪看板数据 + 客退数据",
        "columns": [
            "sn_no", "sku_name", "sku", "brand", "model_number", "foundry",
            "production_date", "product_order", "product_process_yield_rate",
            "sell_time", "sell_order", "sell_check_batch_yield", "return_time",
            "service_order_number", "maintain_factory", "factory_return_batch",
            "accept_reason", "fault_name", "dispose_method", "work_order_type",
            "return_exchange_type", "state", "filter_sealed_status", "retest_result",
            "defect_cause", "defect_material", "defect_material_supplier",
            "responsibility_owner", "repair_man_hours", "repair_cost",
        ],
        "column_mapping": {
            "sn_no": "SN", "sku_name": "SKU名称", "sku": "SKU", "brand": "品牌",
            "model_number": "型号", "foundry": "代工厂", "production_date": "生产日期",
            "product_order": "生产订单号", "product_process_yield_rate": "产品制程直通率",
            "sell_time": "出货日期", "sell_order": "出货订单号",
            "sell_check_batch_yield": "出货检验批次合格率", "return_time": "退货时间",
            "service_order_number": "服务工单号", "maintain_factory": "维修工厂",
            "factory_return_batch": "工厂统计客退批次", "accept_reason": "受理原因",
            "fault_name": "故障名称", "dispose_method": "处理方法",
            "work_order_type": "工单业务类型", "return_exchange_type": "退换货类型",
            "state": "状态", "filter_sealed_status": "滤芯是否拆封",
            "retest_result": "复测结果", "defect_cause": "不良原因",
            "defect_material": "不良物料", "defect_material_supplier": "不良物料供应商",
            "responsibility_owner": "责任归属", "repair_man_hours": "维修工时",
            "repair_cost": "维修费用",
        },
    },
    "sn_quality_key_material": {
        "description": "SN中使用的关键物料的IQC和采购数据（仅同步有客退数据的SN）",
        "source": "成品质量追踪看板数据",
        "columns": [
            "sn_no", "material_code", "material_name", "batch_yield",
            "supplier_name", "purchase_info",
        ],
        "column_mapping": {
            "sn_no": "SN", "material_code": "物料编码", "material_name": "物料名称",
            "batch_yield": "批次合格率", "supplier_name": "供应商",
            "purchase_info": "采购订单号&采购批次号(json)",
        },
    },
    "supplier_quality_iqc": {
        "description": "供应商IQC数据",
        "source": "IQC数据",
        "columns": [
            "supplier_name", "supply_type", "factory_name", "iqc_batch",
            "qualified_batch", "incoming_material_quantity",
            "sampling_inspection_quantity", "return_quantity", "reject_rate",
            "iqc_batch_pass_rate",
        ],
        "column_mapping": {
            "supplier_name": "供应商", "supply_type": "供货类型",
            "factory_name": "代工厂", "iqc_batch": "进料批次",
            "qualified_batch": "合格批次", "incoming_material_quantity": "进料数量",
            "sampling_inspection_quantity": "抽检数量", "return_quantity": "退货数量",
            "reject_rate": "退货率", "iqc_batch_pass_rate": "进料检验批次合格率",
        },
    },
    "supplier_quality_iqc_monthly": {
        "description": "供应商月度进料批次检验合格率、退货率数据",
        "source": "IQC数据",
        "columns": ["supplier_name", "ic_month", "iqc_batch_pass_rate", "reject_rate"],
        "column_mapping": {
            "supplier_name": "供应商", "ic_month": "进料月份",
            "iqc_batch_pass_rate": "进料检验批次合格率", "reject_rate": "退货率",
        },
    },
    "supplier_performance_comparison": {
        "description": "供应商横向对比数据",
        "source": "IQC数据",
        "columns": [
            "material_code", "material_name", "supplier_name", "supply_batch",
            "batch_yield", "supply_quantity", "supply_ratio", "average_price",
            "return_quantity", "return_rate",
        ],
        "column_mapping": {
            "material_code": "物料编码", "material_name": "物料名称",
            "supplier_name": "供应商", "supply_batch": "供货批次",
            "batch_yield": "批次合格率", "supply_quantity": "供货数量",
            "supply_ratio": "供货比例", "average_price": "平均价格",
            "return_quantity": "退货数量", "return_rate": "退货率",
        },
    },
    "sku_quality": {
        "description": "SKU的生产、出货和客退质量数据（当前不可用）",
        "source": "PQC、OQC和客退数据",
        "columns": [
            "sku_name", "production_factory", "yield_rate",
            "oqc_batch_pass_rate", "uph", "cumulative_return_rate",
            "cumulative_fault_rate", "ntf_rate", "seven_no_unreasonable_rate",
            "should_return_rate", "retest_completion_rate", "repair_completion_rate",
            "production_count", "production_qualified_count", "shipment_batch_count",
            "shipment_qualified_batch_count", "shipment_count", "return_count",
            "fault_count", "ntf_count", "seven_no_unreasonable_count", "should_return_count",
        ],
        "column_mapping": {
            "sku_name": "SKU名称", "production_factory": "生产工厂",
            "yield_rate": "直通率", "oqc_batch_pass_rate": "出货检验批次合格率",
            "uph": "UPH", "cumulative_return_rate": "累计退货率",
            "cumulative_fault_rate": "累计故障率", "ntf_rate": "NTF率",
            "seven_no_unreasonable_rate": "7无不合理率", "should_return_rate": "应回退率",
            "retest_completion_rate": "复测完成率", "repair_completion_rate": "返修完成率",
            "production_count": "生产数", "production_qualified_count": "生产合格数",
            "shipment_batch_count": "出货批次数",
            "shipment_qualified_batch_count": "出货检验合格批次数",
            "shipment_count": "出货数", "return_count": "客退数",
            "fault_count": "故障数", "ntf_count": "NTF数",
            "seven_no_unreasonable_count": "7无不合理数", "should_return_count": "应回退数",
        },
    },
    "sku_quality_monthly": {
        "description": "SKU月度质量数据（当前不可用）",
        "source": "PQC、OQC和客退数据",
        "columns": [
            "sku_name", "production_factory", "month", "yield_rate",
            "oqc_batch_pass_rate", "uph", "cumulative_return_rate",
            "current_return_rate", "cumulative_fault_rate", "current_fault_rate",
            "ntf_rate", "seven_no_unreasonable_rate", "should_return_rate",
            "retest_completion_rate", "repair_completion_rate", "production_count",
            "production_qualified_count", "shipment_batch_count",
            "shipment_qualified_batch_count", "shipment_count", "return_count",
            "fault_count", "ntf_count", "seven_no_unreasonable_count", "should_return_count",
        ],
        "column_mapping": {
            "sku_name": "SKU名称", "production_factory": "生产工厂", "month": "月份",
            "yield_rate": "直通率", "oqc_batch_pass_rate": "出货检验批次合格率",
            "uph": "UPH", "cumulative_return_rate": "累计退货率",
            "current_return_rate": "当期退货率", "cumulative_fault_rate": "累计故障率",
            "current_fault_rate": "当期故障率", "ntf_rate": "NTF率",
            "seven_no_unreasonable_rate": "7无不合理率", "should_return_rate": "应回退率",
            "retest_completion_rate": "复测完成率", "repair_completion_rate": "返修完成率",
            "production_count": "生产数", "production_qualified_count": "生产合格数",
            "shipment_batch_count": "出货批次数",
            "shipment_qualified_batch_count": "出货检验合格批次数",
            "shipment_count": "出货数", "return_count": "客退数",
            "fault_count": "故障数", "ntf_count": "NTF数",
            "seven_no_unreasonable_count": "7无不合理数", "should_return_count": "应回退数",
        },
    },
    "factory_quality": {
        "description": "代工厂的进料、生产、出货和客退质量数据（当前不可用）",
        "source": "IQC、PQC、OQC和客退数据",
        "columns": [
            "production_factory", "iqc_batch_pass_rate", "yield_rate",
            "oqc_batch_pass_rate", "uph", "cumulative_return_rate",
            "cumulative_fault_rate", "ntf_rate", "seven_no_unreasonable_rate",
            "should_return_rate", "retest_completion_rate", "repair_completion_rate",
            "incoming_material_quantity", "incoming_batch", "incoming_qualified_batch",
            "production_count", "production_qualified_count", "shipment_batch_count",
            "shipment_qualified_batch_count", "shipment_count", "return_count",
            "fault_count", "ntf_count", "seven_no_unreasonable_count", "should_return_count",
        ],
        "column_mapping": {
            "production_factory": "生产工厂", "iqc_batch_pass_rate": "进料检验批次合格率",
            "yield_rate": "直通率", "oqc_batch_pass_rate": "出货检验批次合格率",
            "uph": "UPH", "cumulative_return_rate": "累计退货率",
            "cumulative_fault_rate": "累计故障率", "ntf_rate": "NTF率",
            "seven_no_unreasonable_rate": "7无不合理率", "should_return_rate": "应回退率",
            "retest_completion_rate": "复测完成率", "repair_completion_rate": "返修完成率",
            "incoming_material_quantity": "进料数量", "incoming_batch": "进料批次",
            "incoming_qualified_batch": "进料合格批次",
            "production_count": "生产数", "production_qualified_count": "生产合格数",
            "shipment_batch_count": "出货批次数",
            "shipment_qualified_batch_count": "出货检验合格批次数",
            "shipment_count": "出货数", "return_count": "客退数",
            "fault_count": "故障数", "ntf_count": "NTF数",
            "seven_no_unreasonable_count": "7无不合理数", "should_return_count": "应回退数",
        },
    },
    "factory_quality_monthly": {
        "description": "代工厂月度的进料、生产、出货和客退质量数据（当前不可用）",
        "source": "IQC、PQC、OQC和客退数据",
        "columns": [
            "production_factory", "month", "iqc_batch_pass_rate", "yield_rate",
            "oqc_batch_pass_rate", "uph", "cumulative_return_rate",
            "current_return_rate", "cumulative_fault_rate", "current_fault_rate",
            "ntf_rate", "seven_no_unreasonable_rate", "should_return_rate",
            "retest_completion_rate", "repair_completion_rate",
            "incoming_material_quantity", "incoming_batch", "incoming_qualified_batch",
            "production_count", "production_qualified_count", "shipment_batch_count",
            "shipment_qualified_batch_count", "shipment_count", "return_count",
            "fault_count", "ntf_count", "seven_no_unreasonable_count", "should_return_count",
        ],
        "column_mapping": {
            "production_factory": "生产工厂", "month": "月份",
            "iqc_batch_pass_rate": "进料检验批次合格率", "yield_rate": "直通率",
            "oqc_batch_pass_rate": "出货检验批次合格率", "uph": "UPH",
            "cumulative_return_rate": "累计退货率", "current_return_rate": "当期退货率",
            "cumulative_fault_rate": "累计故障率", "current_fault_rate": "当期故障率",
            "ntf_rate": "NTF率", "seven_no_unreasonable_rate": "7无不合理率",
            "should_return_rate": "应回退率", "retest_completion_rate": "复测完成率",
            "repair_completion_rate": "返修完成率",
            "incoming_material_quantity": "进料数量", "incoming_batch": "进料批次",
            "incoming_qualified_batch": "进料合格批次",
            "production_count": "生产数", "production_qualified_count": "生产合格数",
            "shipment_batch_count": "出货批次数",
            "shipment_qualified_batch_count": "出货检验合格批次数",
            "shipment_count": "出货数", "return_count": "客退数",
            "fault_count": "故障数", "ntf_count": "NTF数",
            "seven_no_unreasonable_count": "7无不合理数", "should_return_count": "应回退数",
        },
    },
    "part_quality": {
        "description": "物料的进货、退货和进料检验批次合格率质量数据（当前不可用）",
        "source": "IQC数据",
        "columns": [
            "material_code", "material_name", "supplier_name", "supply_batch",
            "average_price", "supply_quantity", "return_quantity",
            "iqc_batch_pass_rate", "return_rate",
        ],
        "column_mapping": {
            "material_code": "物料编码", "material_name": "物料名称",
            "supplier_name": "供应商", "supply_batch": "供货批次",
            "average_price": "平均价格", "supply_quantity": "供货数量",
            "return_quantity": "退货数量", "iqc_batch_pass_rate": "进料检验批次合格率",
            "return_rate": "退货率",
        },
    },
    "part_quality_monthly": {
        "description": "物料月度的进货、退货和进料检验批次合格率质量数据（当前不可用）",
        "source": "IQC数据",
        "columns": [
            "material_code", "material_name", "month", "supplier_name",
            "supply_batch", "average_price", "supply_quantity", "return_quantity",
            "iqc_batch_pass_rate", "return_rate",
        ],
        "column_mapping": {
            "material_code": "物料编码", "material_name": "物料名称", "month": "月份",
            "supplier_name": "供应商", "supply_batch": "供货批次",
            "average_price": "平均价格", "supply_quantity": "供货数量",
            "return_quantity": "退货数量", "iqc_batch_pass_rate": "进料检验批次合格率",
            "return_rate": "退货率",
        },
    },
    "iqc_ng": {
        "description": "全量IQC抽检不合格数据（当前不可用）",
        "source": "IQC数据",
        "columns": [
            "factory_name", "material_code", "material_name", "supplier_name",
            "inspection_order", "delivery_order", "inspection_time",
            "submitted_quantity", "inspected_quantity", "inspection_result",
            "inspection_detail",
        ],
        "column_mapping": {
            "factory_name": "代工厂", "material_code": "物料编码",
            "material_name": "物料名称", "supplier_name": "供应商",
            "inspection_order": "检验单号", "delivery_order": "送货单号",
            "inspection_time": "抽检时间", "submitted_quantity": "送检数量",
            "inspected_quantity": "抽检数量", "inspection_result": "抽检结果",
            "inspection_detail": "检验明细",
        },
    },
    "pqc_ng": {
        "description": "全量PQC维修数据（当前不可用）",
        "source": "PQC数据",
        "columns": [
            "factory_name", "sn_no", "sku", "sku_name",
            "fault_symptom_category", "fault_symptom_name",
            "fault_cause_category", "fault_cause_name",
            "defect_responsibility", "repair_method", "repair_time",
        ],
        "column_mapping": {
            "factory_name": "代工厂", "sn_no": "SN", "sku": "SKU",
            "sku_name": "SKU名称", "fault_symptom_category": "故障现象分类名称",
            "fault_symptom_name": "故障现象名称",
            "fault_cause_category": "故障原因分类名称",
            "fault_cause_name": "故障原因名称",
            "defect_responsibility": "不良责任名称",
            "repair_method": "维修方法名称", "repair_time": "维修时间",
        },
    },
    "oqc_ng": {
        "description": "全量OQC抽检不合格数据（当前不可用）",
        "source": "OQC数据",
        "columns": [
            "factory_name", "inspection_order", "sku", "sku_name",
            "sampling_time", "submitted_quantity", "required_quantity",
            "inspected_quantity", "judgment_result", "nonconformity_disposal",
            "inspection_detail",
        ],
        "column_mapping": {
            "factory_name": "代工厂", "inspection_order": "检验单号",
            "sku": "SKU", "sku_name": "SKU名称", "sampling_time": "抽样时间",
            "submitted_quantity": "送检数", "required_quantity": "应抽数",
            "inspected_quantity": "实抽数", "judgment_result": "判定结果",
            "nonconformity_disposal": "不合格处置", "inspection_detail": "检验明细",
        },
    },
    "return_data": {
        "description": "全量客退数据",
        "source": "客退数据",
        "columns": [
            "sn_no", "return_time", "service_order_number", "is_special_appraisal",
            "sku", "sku_name", "factory_return_batch", "production_factory",
            "return_factory", "accept_reason", "fault_name", "dispose_method",
            "work_order_type", "return_exchange_type", "state",
            "filter_sealed_status", "retest_result", "defect_cause",
            "defect_material", "defect_material_batch", "defect_material_supplier",
            "lack_material", "responsibility_owner", "repair_man_hours", "repair_cost",
        ],
        "column_mapping": {
            "sn_no": "SN", "return_time": "客退日期",
            "service_order_number": "服务工单号",
            "is_special_appraisal": "是否特批/技术鉴定",
            "sku": "SKU", "sku_name": "SKU名称",
            "factory_return_batch": "工厂统计客退批次",
            "production_factory": "生产工厂", "return_factory": "退回工厂",
            "accept_reason": "受理原因", "fault_name": "故障名称",
            "dispose_method": "处理方法", "work_order_type": "工单业务类型",
            "return_exchange_type": "退换货类型", "state": "处理状态",
            "filter_sealed_status": "滤芯是否拆封", "retest_result": "复测结果",
            "defect_cause": "不良原因", "defect_material": "不良物料",
            "defect_material_batch": "不良物料批次号",
            "defect_material_supplier": "不良物料供应商",
            "lack_material": "缺少物料", "responsibility_owner": "责任归属",
            "repair_man_hours": "维修工时(h)", "repair_cost": "维修成本",
        },
    },
    "maintain_consume_material": {
        "description": "维修消耗的物料数据",
        "source": "客退数据",
        "columns": ["sn_no", "maintain_material_code", "maintain_material_name", "consume_material_count"],
        "column_mapping": {
            "sn_no": "SN", "maintain_material_code": "物料编码",
            "maintain_material_name": "物料名称", "consume_material_count": "数量",
        },
    },
}

# ======================== Agent 路由配置 ========================
# 主控Agent根据用户意图路由到对应子Agent
AGENT_ROUTING = {
    "sn_trace": {
        "name": "SN溯源Agent",
        "description": "通过SN查询全链路质量数据，包括生产、出货、客退和关键物料信息",
        "tables": ["sn_quality_data", "sn_quality_key_material"],
        "keywords": ["SN", "序列号", "溯源", "追溯", "工单", "维修"],
    },
    "supplier": {
        "name": "供应商质量Agent",
        "description": "查询和分析供应商质量数据，包括IQC合格率、退货率、月度趋势和横向对比",
        "tables": ["supplier_quality_iqc", "supplier_quality_iqc_monthly", "supplier_performance_comparison"],
        "keywords": ["供应商", "供货", "IQC", "进料", "来料"],
    },
    "sku": {
        "name": "SKU分析Agent",
        "description": "查询和分析SKU维度的质量数据，包括直通率、退货率、故障率、月度趋势",
        "tables": ["sku_quality", "sku_quality_monthly"],
        "keywords": ["SKU", "产品", "品类", "型号"],
    },
    "factory": {
        "name": "代工厂质量Agent",
        "description": "查询和分析代工厂维度的质量数据，包括进料、生产、出货、客退全流程",
        "tables": ["factory_quality", "factory_quality_monthly"],
        "keywords": ["代工厂", "工厂", "生产工厂", "制造"],
    },
    "material": {
        "name": "物料质量Agent",
        "description": "查询和分析物料维度的质量数据，包括进货、退货、合格率",
        "tables": ["part_quality", "part_quality_monthly"],
        "keywords": ["物料", "零部件", "元件", "Part"],
    },
    "root_cause": {
        "name": "根因分析Agent",
        "description": "基于NG记录和客退数据进行根因分析，涉及IQC/PQC/OQC不合格和客退故障",
        "tables": ["iqc_ng", "pqc_ng", "oqc_ng", "return_data", "maintain_consume_material"],
        "keywords": ["根因", "原因", "NG", "不合格"],
    },
    "return_analysis": {
        "name": "客退分析Agent",
        "description": "查询和分析客退数据，包括按SKU/工厂/故障/时间等维度的客退统计、趋势分析、退货原因分布、维修成本分析，以及维修消耗物料分析",
        "tables": ["return_data", "maintain_consume_material"],
        "keywords": ["客退", "退货", "退换货", "故障", "维修", "返修", "工单", "售后", "维修成本", "维修工时"],
    },
}
