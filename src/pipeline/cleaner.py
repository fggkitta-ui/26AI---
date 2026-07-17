"""
内容清洗模块。

职责：
1. 去除导航栏/广告/页脚/重复模板文字等噪声，只保留正文有效信息
2. 按用户意图（keyword/region/time_range）二次过滤不符合条件的条目
"""

import re
from typing import List
from datetime import datetime

from src.adapters.base_adapter import RawTenderItem

# TODO: 根据实际抓取到的页面样本，补充更多噪声模式
NOISE_PATTERNS = [
    r"版权所有.*?保留所有权利",
    r"联系电话[:：].{0,30}",
    r"扫一扫[，,]?关注公众号",
    r"Copyright.*?\d{4}",
]


def strip_noise(raw_html_or_text: str) -> str:
    """去除已知的导航/广告/模板类噪声文本。"""
    text = raw_html_or_text
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)
    # 合并多余空白
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text


def matches_filters(item: RawTenderItem, keyword: str, region: str,
                     start_date: datetime, end_date: datetime) -> bool:
    """
    校验单条信息是否符合用户意图中的筛选条件。
    TODO: keyword 匹配建议做同义词/近似匹配（如"充电桩"应能匹配到
    "新能源汽车充电设施"），可结合简单的同义词表或 embedding 相似度。
    """
    if keyword and keyword not in item.title and keyword not in item.content:
        return False
    if region and region not in item.title and region not in item.content:
        return False
    if item.publish_time and not (start_date <= item.publish_time <= end_date):
        return False
    return True


def clean_items(items: List[RawTenderItem], keyword: str, region: str,
                 start_date: datetime, end_date: datetime) -> List[RawTenderItem]:
    cleaned = []
    for item in items:
        item.content = strip_noise(item.content)
        if matches_filters(item, keyword, region, start_date, end_date):
            cleaned.append(item)
    return cleaned
