"""
汇总生成模块。

赛题核心要求："核心内容必须与原文事实一致"，"必须有可追溯性/引用原文机制"。

策略（两层）：
1.「抽取式摘要」—— 用规则从原文中识别并保留关键句子（预算金额、项目概况、
   投标截止时间、招标人/中标人等），不做任何改写，保证 100% 事实一致。
2.「LLM 精炼」（可选）—— 对抽取结果做语言压缩（去冗余连接词），但严格约束
   "只压缩不编造"，Prompt 中明确要求保留数字/日期/机构名原样。

字段严格按照赛题要求的五要素输出：
- 标题
- 发布时间
- 来源链接（原文 URL）
- 核心内容（摘要，与原文事实一致）
- 附件链接（如有）
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime
import re

from src.adapters.base_adapter import RawTenderItem


@dataclass
class SummarizedItem:
    """汇总后的标准输出结构，对应赛题要求的五要素。"""

    title: str
    publish_time: str               # 格式化后的日期字符串
    source_url: str
    core_content: str               # 核心内容摘要（事实一致的抽取式摘要）
    attachment_urls: List[str] = field(default_factory=list)
    # 附加元信息（便于追溯）
    source_name: str = ""
    original_content_snippet: str = ""  # 保留原文前 500 字供核验


# ---------------------------------------------------------------------------
# 关键信息识别正则（用于抽取式摘要）
# ---------------------------------------------------------------------------

# 高价值句子模式 —— 从原文中优先抽取包含以下信息的句子
KEY_INFO_PATTERNS = [
    # 项目编号
    (r"项目(?:编号|代码)[：:]\s*[A-Za-z0-9\-]+", 5),
    # 预算/金额
    (r"(?:预算|投资|中标|成交|合同)\s*(?:金额|价|总价|总额)[：:]\s*\d[\d.,，万佰仟亿元]*", 5),
    (r"\d[\d.,，]*\s*(?:万元|亿元|元)", 4),
    # 项目概况/采购需求
    (r"(?:项目|采购)\s*(?:概况|需求|内容|规模)[：:]", 4),
    (r"(?:建设|采购|招标)\s*(?:规模|内容|范围)[：:]", 4),
    # 时间节点
    (r"(?:投标截止|开标|递交截止)[^。\n]{0,30}(?:时间|日期)[：:].*?(?:\d{4}年\d{1,2}月\d{1,2}日|\d{2}:\d{2})", 4),
    (r"(?:获取|下载)\s*招标文件.*?(?:时间|期限)[：:].*", 3),
    # 招标人/采购人/中标人
    (r"(?:招标人|采购人|招标单位|采购单位|中标人|中标单位|供应商)[：:]\s*.{2,40}", 4),
    # 合同履行期限/工期
    (r"(?:合同\s*履行\s*期限|工期|服务期|供货期)[：:].*", 3),
    # 地点/区域
    (r"(?:建设|交货|服务|项目)\s*(?:地点|地址|区域)[：:].*", 3),
    # 联系方式
    (r"(?:联系人|联系电话)[：:].*", 1),
]


def _score_sentence(sentence: str) -> int:
    """根据包含的关键信息量给句子打分。"""
    score = 0
    for pattern, weight in KEY_INFO_PATTERNS:
        if re.search(pattern, sentence):
            score += weight
    return score


def extract_key_sentences(content: str, max_sentences: int = 5) -> str:
    """
    基于关键信息权重的抽取式摘要。

    步骤：
    1. 将原文按句号/换行分句
    2. 对每个句子按"是否包含项目编号/预算金额/招标人/时间节点等关键信息"打分
    3. 按分数排序，取 Top-N 个句子
    4. 保持句子原始顺序重组，确保语义连贯
    5. 截断过长的句子，保留前 200 字符

    注意：此方法保持原文措辞不变，仅做"信息密度筛选"，
    从根本上杜绝 LLM 生成式摘要可能引入的事实性错误。
    """
    if not content:
        return "（暂无内容）"

    # 分句：句号、换行、分号
    raw_sentences = re.split(r"[。\n；;]", content)
    sentences = [s.strip() for s in raw_sentences if len(s.strip()) > 5]

    if not sentences:
        return content[:300] + ("..." if len(content) > 300 else "")

    # 对每个句子打分
    scored = [(s, _score_sentence(s)) for s in sentences]

    # 过滤掉得分为 0 的句子（无关键信息）
    meaningful = [(s, sc) for s, sc in scored if sc > 0]

    if not meaningful:
        # 如果所有句子都没有关键信息特征，返回前几句
        meaningful = [(s, 0) for s in sentences[:max_sentences]]

    # 按得分排序取 Top-N，保持原文顺序
    top_indices = sorted(
        range(len(meaningful)),
        key=lambda i: meaningful[i][1],
        reverse=True,
    )[:max_sentences]

    # 按原文出现顺序重排
    selected = [meaningful[i][0] for i in sorted(top_indices)]

    # 截断过长句子
    result = []
    for s in selected:
        if len(s) > 200:
            s = s[:200] + "..."
        result.append(s)

    return "；".join(result) + "。"


def summarize(items: List[RawTenderItem]) -> List[SummarizedItem]:
    """对清洗去重后的条目进行汇总，生成标准五要素结构。"""
    results = []
    for item in items:
        core_content = extract_key_sentences(item.content)

        # 如果抽取结果过短，补充开头部分作为上下文
        if len(core_content) < 30 and item.content:
            core_content = item.content[:300] + ("..." if len(item.content) > 300 else "")

        results.append(SummarizedItem(
            title=item.title,
            publish_time=item.publish_time.strftime("%Y-%m-%d") if item.publish_time else "未知",
            source_url=item.source_url,
            core_content=core_content,
            attachment_urls=item.attachment_urls,
            source_name=item.source_name,
            original_content_snippet=item.content[:500],
        ))
    return results


def to_dict_list(items: List[SummarizedItem]) -> List[dict]:
    """将汇总结果转为 dict 列表（方便 JSON 序列化/API 返回）。"""
    return [asdict(i) for i in items]
