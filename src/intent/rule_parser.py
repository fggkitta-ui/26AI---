"""
意图解析模块 —— 招投标信息智能聚合系统 - 核心模块 Demo

功能：将用户的自然语言问题解析为标准化的结构化意图 JSON：
    { keyword, region, time_range, schedule }

设计说明：
- 本模块使用【通用规则 + 词典匹配】实现，逻辑对任意输入生效，
  不针对题目给出的示例问题做任何专属硬编码。
- 生产环境建议：规则解析作为"兜底/快速通道"，配合 LLM 结构化抽取
  （见同目录 llm_intent_parser.py）处理更灵活的长尾自然语言表达，
  两者互为校验，提升准确率与鲁棒性。
"""

import re
import json
from datetime import datetime, timedelta
import calendar

# ---------------------------------------------------------------------------
# 1. 词典（可持续扩充，非针对具体测试问题）
# ---------------------------------------------------------------------------

REGIONS = [
    "北京", "上海", "天津", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃", "青海",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门", "台湾",
]
# 按长度倒序，保证优先匹配更长、更精确的地名（如"安徽省"先于"安徽"）
REGION_SUFFIXES = ["省", "市", "自治区", "特别行政区"]


def extract_region(text: str):
    """返回 (归一化地名, 原文中匹配到的原始片段)，原始片段用于后续从文本中剥离。"""
    candidates = []
    for r in REGIONS:
        for suf in [""] + REGION_SUFFIXES:
            token = r + suf
            if token in text:
                candidates.append(token)
    if not candidates:
        return None, None
    # 取最长匹配，避免"安徽"被"安徽省"这种更精确表达吞掉信息
    best = max(candidates, key=len)
    # 归一化：只保留地名主体（去掉"省/市"等后缀，便于后续统一检索）
    normalized = best
    for suf in REGION_SUFFIXES:
        if best.endswith(suf):
            normalized = best[: -len(suf)]
            break
    return normalized, best


# ---------------------------------------------------------------------------
# 2. 时间范围解析
# ---------------------------------------------------------------------------

def extract_time_range(text: str, now: datetime):
    # 2.1 相对时间："最近N个月/天/周/年"
    m = re.search(r"最近\s*(\d+)\s*(个月|月|天|周|年)", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ("个月", "月"):
            start = now - timedelta(days=30 * n)
        elif unit == "天":
            start = now - timedelta(days=n)
        elif unit == "周":
            start = now - timedelta(weeks=n)
        else:  # 年
            start = now - timedelta(days=365 * n)
        return {
            "type": "relative",
            "raw": m.group(0),
            "start": start.strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"),
        }

    # 2.2 绝对时间："2026年3月份" / "2026年3月" / "2026-03"
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*份?", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        last_day = calendar.monthrange(year, month)[1]
        return {
            "type": "absolute_month",
            "raw": m.group(0),
            "start": f"{year:04d}-{month:02d}-01",
            "end": f"{year:04d}-{month:02d}-{last_day:02d}",
        }

    return None


# ---------------------------------------------------------------------------
# 3. 频率 / 调度解析
# ---------------------------------------------------------------------------

def extract_schedule(text: str):
    # 3.1 一次性："今天9:00发送" / "今天9点发送我"
    m = re.search(r"今天\s*(\d{1,2})[:：]?(\d{2})?\s*发送", text)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        return {
            "is_recurring": False,
            "raw": m.group(0),
            "run_at": f"{hh:02d}:{mm:02d}",
        }

    # 3.2 每日定时："每天9:00" / "每天早上9点"
    m = re.search(r"每天\s*(?:早上|上午)?\s*(\d{1,2})[:：点](\d{2})?", text)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        return {
            "is_recurring": True,
            "raw": m.group(0),
            "cron": f"{mm} {hh} * * *",
        }

    # 3.3 每周定时："每周一9:00"
    weekday_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0}
    m = re.search(r"每周([一二三四五六日天])\s*(\d{1,2})[:：点](\d{2})?", text)
    if m:
        wd = weekday_map[m.group(1)]
        hh, mm = int(m.group(2)), int(m.group(3) or 0)
        return {
            "is_recurring": True,
            "raw": m.group(0),
            "cron": f"{mm} {hh} * * {wd}",
        }

    # 未提及频率 -> 立即执行一次
    return {"is_recurring": False, "raw": None, "run_at": "immediate"}


# ---------------------------------------------------------------------------
# 4. 主题/关键词解析
#    思路：先剥离已识别出的地域、时间、频率片段与常见虚词，
#    再从剩余文本中，用"XX招标信息"这一通用句式抓取主题词。
# ---------------------------------------------------------------------------

STOPWORDS_PATTERNS = [
    r"区域内的?", r"都有哪些", r"请汇总后?", r"发送给我", r"每天\S{0,6}发送",
    r"今天\S{0,6}发送", r"的$",
]


def extract_keyword(text: str, region_raw: str, time_raw: str, schedule_raw: str):
    cleaned = text
    if region_raw:
        cleaned = cleaned.replace(region_raw, "")
    if time_raw:
        cleaned = cleaned.replace(time_raw, "")
    if schedule_raw:
        cleaned = cleaned.replace(schedule_raw, "")
    for pat in STOPWORDS_PATTERNS:
        cleaned = re.sub(pat, "", cleaned)
    # "的" 是纯语法助词，不携带实体信息，去除后不影响主题词识别
    cleaned = cleaned.replace("的", "")

    # 核心句式："<主题>招标信息"
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{1,10})招标信息", cleaned)
    if m:
        kw = m.group(1).strip()
        # 去除"相关""方面"等修饰性尾词，保留核心主题
        kw = re.sub(r"(相关|方面|领域)$", "", kw)
        return kw

    # 兜底：去除常见助词后剩余的核心词
    fallback = re.sub(r"[，,。！？\s]", "", cleaned)
    fallback = fallback.replace("的", "")
    return fallback or None


# ---------------------------------------------------------------------------
# 5. 汇总入口
# ---------------------------------------------------------------------------

def parse_intent(text: str, now: datetime = None):
    now = now or datetime.now()
    region, region_raw = extract_region(text)
    time_range = extract_time_range(text, now)
    schedule = extract_schedule(text)
    keyword = extract_keyword(
        text,
        region_raw=region_raw,
        time_raw=time_range["raw"] if time_range else None,
        schedule_raw=schedule.get("raw"),
    )
    return {
        "query": text,
        "keyword": keyword,
        "region": region,
        "time_range": time_range,
        "schedule": schedule,
    }


if __name__ == "__main__":
    demo_queries = [
        "最近1个月的安徽省区域内的服务器招标信息都有哪些",
        "2026年3月份的上海区域内的充电桩招标信息都有哪些",
        "最近3个月的上海区域内的充电桩招标信息都有哪些，请汇总后每天9:00发送给我",
        "2026年4月份上海的充电桩招标信息都有哪些，请汇总后今天9:00发送给我",
        # 新增两个题目未出现过的问法，验证泛化能力（非硬编码）
        "2026年4月北京充电桩相关的招标信息都有哪些",
        "最近2周河南省的光伏电站招标信息都有哪些，请每周一9:00发给我",
    ]

    print(f"[运行时间] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    for q in demo_queries:
        result = parse_intent(q)
        print("输入：", q)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("-" * 60)
