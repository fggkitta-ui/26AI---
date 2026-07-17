"""
汇总生成模块。

赛题要求："核心内容必须与原文事实一致"，因此摘要生成需要做到可追溯、
可核验，而不是让大模型自由发挥。本模块采用"抽取式摘要为主 + LLM
精炼语言表达为辅"的策略，避免纯生成式摘要可能引入的事实性错误。
"""

from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime

from src.adapters.base_adapter import RawTenderItem


@dataclass
class SummarizedItem:
    """汇总后的标准输出结构，对应赛题要求的五要素。"""

    title: str
    publish_time: Optional[str]      # 格式化后的字符串，便于直接写入文档
    source_url: str
    core_content: str                # 核心内容摘要
    attachment_urls: List[str]


def extract_key_sentences(content: str, max_sentences: int = 3) -> str:
    """
    抽取式摘要：优先保留包含关键信息的句子
    （预算金额、项目名称、截止时间等），而不是重新生成文字。
    TODO: 可结合正则识别"预算金额""投标截止时间""招标人"等关键句，
    优先保留；也可调用 LLM 做"仅压缩、不改写事实"的摘要，
    Prompt 需明确要求"禁止编造原文未提及的信息"。
    """
    sentences = [s.strip() for s in content.replace("\n", "。").split("。") if s.strip()]
    return "。".join(sentences[:max_sentences]) + ("。" if sentences else "")


def summarize(items: List[RawTenderItem]) -> List[SummarizedItem]:
    results = []
    for item in items:
        results.append(SummarizedItem(
            title=item.title,
            publish_time=item.publish_time.strftime("%Y-%m-%d") if item.publish_time else "未知",
            source_url=item.source_url,
            core_content=extract_key_sentences(item.content),
            attachment_urls=item.attachment_urls,
        ))
    return results


def to_dict_list(items: List[SummarizedItem]) -> List[dict]:
    return [asdict(i) for i in items]
