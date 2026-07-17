"""
去重模块。

思路：
- 同一条招投标信息经常被政府平台 + 多个商业聚合站同时收录/转载，
  标题、发布时间、正文高度相似但不完全一致（转载时可能有细微改写）。
- 用"标题归一化 + 发布日期 + 正文前 N 字"生成指纹哈希，作为初筛；
  如需更高精度，可在此基础上升级为 embedding 余弦相似度去重
  （见下方 TODO）。
"""

import hashlib
import re
from typing import List

from src.adapters.base_adapter import RawTenderItem


def normalize_title(title: str) -> str:
    """去除标点、空白、常见前缀（如"关于""公告"）后的归一化标题。"""
    title = re.sub(r"[\s　，,。！？【】\[\]()（）]", "", title)
    title = re.sub(r"^(关于|公告|通知)", "", title)
    return title.lower()


def fingerprint(item: RawTenderItem) -> str:
    date_part = item.publish_time.strftime("%Y%m%d") if item.publish_time else ""
    content_snippet = re.sub(r"\s", "", item.content)[:200]
    raw = normalize_title(item.title) + date_part + content_snippet
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def deduplicate(items: List[RawTenderItem]) -> List[RawTenderItem]:
    seen = set()
    unique_items = []
    for item in items:
        fp = fingerprint(item)
        if fp not in seen:
            seen.add(fp)
            unique_items.append(item)
    return unique_items

# TODO（进阶）：
# 若指纹哈希对"标题改写幅度较大的转载"漏检，可引入 embedding 相似度：
#   1. 用 sentence-transformers 或调用 Embedding API 生成每条内容的向量
#   2. 计算两两余弦相似度，超过阈值（如 0.9）视为重复
#   3. 该方案计算成本更高，建议先用指纹哈希粗筛，再对疑似重复做精细比对
