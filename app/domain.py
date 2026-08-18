from __future__ import annotations

import re


PRODUCT_CATEGORY_RULES = {
    "3C数码": ["audio", "cine", "computer", "consoles", "electronics", "pcs", "tablets", "telefonia", "games", "office", "cool_stuff"],
    "生鲜": ["food", "drinks"],
    "服饰": ["fashion", "luggage", "shoes", "watches", "bed_bath"],
    "美妆": ["beauty", "perfumery", "health"],
}

CATEGORY_QUERY_MAP = {
    "手机": "3C数码",
    "电脑": "3C数码",
    "耳机": "3C数码",
    "电子": "3C数码",
    "数码": "3C数码",
    "生鲜": "生鲜",
    "水果": "生鲜",
    "食品": "生鲜",
    "服饰": "服饰",
    "衣服": "服饰",
    "鞋": "服饰",
    "美妆": "美妆",
    "护肤": "美妆",
    "香水": "美妆",
}

COMPLAINT_PATTERNS = {
    "物流延误": ["delay", "late", "atras", "demora", "entrega", "nao chegou", "não chegou", "物流", "延误"],
    "质量问题": ["defeito", "queb", "ruim", "broken", "bad", "quality", "problem", "defect", "质量"],
    "包装破损": ["embal", "amass", "damag", "box", "package", "packing", "破损", "包装"],
    "仅退款": ["refund", "reembolso", "devol", "cancel", "troca", "退款"],
}

MUTATION_PATTERNS = [
    "update", "delete", "insert", "drop", "truncate", "删除", "清空", "审批", "批了",
    "通过退款", "改订单", "直接退款", "退款额度调到", "调整退款额度", "修改退款额度",
    "工单的优先级设为", "工单优先级设为", "设置工单优先级", "调整工单优先级",
]
PROMPT_INJECTION_PATTERNS = [
    "忽略规则",
    "忽略上面的规则",
    "忽略之前",
    "忽略系统",
    "绕过",
    "越权",
    "无视权限",
    "system prompt",
    "developer message",
    "ignore previous",
    "ignore all previous",
]
DATA_EXFILTRATION_PATTERNS = [
    "导出全部用户",
    "导出所有用户",
    "全部用户",
    "全量用户",
    "dump all",
    "export all users",
    "所有 user_id",
    "全部 user_id",
]
QUERY_PATTERNS = ["查询", "查一下", "明细", "退款", "赔付", "订单", "统计", "分析", "风险", "用户"]
POLICY_PATTERNS = ["政策", "规则", "SOP", "怎么赔", "能不能退", "如何处理", "依据", "条款", "规范", "怎么处理", "应该怎么", "how to", "should we", "policy"]


def classify_category(raw_value: str) -> str:
    raw = (raw_value or "").lower()
    for mapped, patterns in PRODUCT_CATEGORY_RULES.items():
        if any(pattern in raw for pattern in patterns):
            return mapped
    return "其他"


def classify_complaint(comment: str, review_score: float) -> str:
    content = (comment or "").lower()
    for complaint_type, patterns in COMPLAINT_PATTERNS.items():
        if any(pattern in content for pattern in patterns):
            return complaint_type
    if review_score <= 2:
        return "质量问题"
    return "一般咨询"


def detect_category_from_query(message: str) -> str | None:
    for keyword, category in CATEGORY_QUERY_MAP.items():
        if keyword in message:
            return category
    return None


def detect_complaint_type(message: str) -> str | None:
    for complaint_type in COMPLAINT_PATTERNS:
        if complaint_type in message:
            return complaint_type
    return None


def detect_amount_threshold(message: str) -> float | None:
    match = re.search(r"(超过|大于|高于)\s*(\d+(?:\.\d+)?)\s*元", message)
    return float(match.group(2)) if match else None


def contains_any(message: str, patterns: list[str]) -> bool:
    lowered = message.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def normalize_category(category: str | None) -> str | None:
    if not category:
        return None
    if category in PRODUCT_CATEGORY_RULES:
        return category
    return CATEGORY_QUERY_MAP.get(category)
