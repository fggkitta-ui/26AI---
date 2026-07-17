"""
内容清洗模块。

职责：
1. 去除导航栏/广告/页脚/重复模板文字等噪声，只保留正文有效信息
2. 按用户意图（keyword/region/time_range）二次过滤不符合条件的条目
3. 支持关键词同义词/近似词匹配，提高筛选召回率

设计思路：
- 噪声模式分三类：HTML 结构噪声、网站模板噪声、内容通用噪声
- 筛选采用"精确匹配 + 同义词扩展 + 宽松匹配"三级策略：
  L1: 精确子串匹配（快速初筛）
  L2: 同义词/近似词扩展（提升召回）
  L3: 放宽条件（无关键词匹配但标题/内容在区域+时间范围内）
"""

import re
from typing import List, Set
from datetime import datetime

from src.adapters.base_adapter import RawTenderItem

# ---------------------------------------------------------------------------
# 同义词/近似词映射表
# 目的：用户说"充电桩"时也能匹配到"新能源汽车充电设施""电动汽车充电站"等
# 扩充方式：可持续从公开词库或 LLM 辅助生成后人工审核加入
# ---------------------------------------------------------------------------
SYNONYM_MAP = {
    "充电桩": ["充电设施", "充电站", "充电基础设施", "电动汽车充电", "新能源充电",
              "快充桩", "慢充桩", "直流充电", "交流充电", "充换电"],
    "服务器": ["计算服务器", "服务器集群", "服务器设备", "数据中心服务器",
              "高性能计算", "HPC", "GPU服务器", "存储服务器", "云服务器"],
    "光伏": ["光伏电站", "太阳能发电", "光伏发电", "分布式光伏", "集中式光伏",
            "光伏组件", "光伏逆变器", "BIPV", "PV"],
    "储能": ["储能电站", "储能系统", "电池储能", "储能设备", "电化学储能",
            "抽水蓄能", "压缩空气储能", "储能电池"],
    "数据中心": ["数据中心", "数据中心建设", "IDC", "机房建设", "云计算中心",
               "大数据中心", "算力中心", "智算中心"],
    "智慧城市": ["智慧城市", "数字城市", "城市大脑", "智慧政务", "智慧交通",
               "城市数字化", "新型智慧城市"],
    "安防": ["安防监控", "视频监控", "安防系统", "安全防范", "智能安防",
            "视频安防", "安防工程", "天网工程"],
    "电力": ["电力工程", "输变电", "配电", "电网", "变电站", "输电线路",
            "电力设施", "电力设备", "供电"],
}

# ---------------------------------------------------------------------------
# 噪声模式
# ---------------------------------------------------------------------------

# A. 通用网页噪声（版权、导航、联系方式等）
GENERIC_NOISE_PATTERNS = [
    r"版权所有[©]?.*?(?:\d{4}|保留)",
    r"Copyright\s*[©]?\s*\d{4}.*?(?:All\s+Rights?\s+Reserved)?",
    r"联系电话[:：]\s*\d[\d\s\-]{6,20}",
    r"联系地址[:：].{0,50}",
    r"扫一扫[，,]?\s*关注\S*公众号",
    r"微信[扫一]?扫",
    r"主办单位[:：].{0,30}",
    r"承办单位[:：].{0,30}",
    r"ICP[备证].*?\d+号?",
    r"建议使用.*?浏览器",
    r"最佳分辨率[:：].*",
    r"网站地图\s*[|/]\s*",
    r"关于我们\s*[|/]\s*联系我们",
]

# B. 招投标网站特有的模板噪声（导航菜单、列表标签等）
TENDER_TEMPLATE_PATTERNS = [
    r"首页\s*[>＞]\s*.*?[>＞]\s*(?:正文|详情|内容)",
    r"当前位置[:：].*",
    r"【浏览次数.*?】",
    r"【打印本页】【关闭窗口】",
    r"【大\s*中\s*小】",
    r"【我要打印】",
    r"发布时间[:：]\s*\d{4}.*?\n",  # 发布时间作为元信息保留，不作为噪声删除
    r"信息发布人[:：].*",
    r"阅读次数[:：]\s*\d+",
    r"字体[:：].*?大.*?小",
    r"视力保护色.*",
    r"索\s*引\s*号[:：].*",
    r"发布机构[:：].*",
    r"成文日期[:：].*",
    r"发文字号[:：].*",
    r"发布日期[:：].*",
    r"生效日期[:：].*",
    r"废止日期[:：].*",
]

# C. HTML 标签清理
HTML_CLEANUP_PATTERNS = [
    (r"<script[^>]*>.*?</script>", "", "删除 script 标签"),
    (r"<style[^>]*>.*?</style>", "", "删除 style 标签"),
    (r"<[^>]+>", " ", "删除所有 HTML 标签"),
    (r"&nbsp;", " ", "替换 &nbsp;"),
    (r"&amp;", "&", "替换 &amp;"),
    (r"&lt;", "<", "替换 &lt;"),
    (r"&gt;", ">", "替换 &gt;"),
    (r"&quot;", '"', "替换 &quot;"),
    (r"&#\d+;", " ", "替换数字实体"),
]


def strip_noise(raw_text: str) -> str:
    """多阶段去除噪声文本。"""
    text = raw_text

    # 第 1 阶段：清理 HTML 标签和实体
    for pattern, replacement, _ in HTML_CLEANUP_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.DOTALL | re.IGNORECASE)

    # 第 2 阶段：删除招投标网站模板内容
    for pattern in TENDER_TEMPLATE_PATTERNS:
        text = re.sub(pattern, "", text)

    # 第 3 阶段：删除通用网页噪声
    for pattern in GENERIC_NOISE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

    # 第 4 阶段：空白规范化
    text = re.sub(r"\r\n", "\n", text)           # Windows 换行统一
    text = re.sub(r"\n{3,}", "\n\n", text)       # 合并多个连续空行（最多保留一个空行）
    text = re.sub(r"[ \t]{2,}", " ", text)       # 合并多个连续空格
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)  # 去掉行首空白

    return text.strip()


def _expand_keywords(keyword: str) -> Set[str]:
    """将关键词扩展为同义词集合，用于宽松匹配。"""
    expanded = {keyword}
    if keyword in SYNONYM_MAP:
        expanded.update(SYNONYM_MAP[keyword])
    # 也检查反向映射：如果 keyword 出现在某个同义词列表中
    for main_kw, synonyms in SYNONYM_MAP.items():
        if keyword in synonyms:
            expanded.add(main_kw)
            expanded.update(synonyms)
    return expanded


def _keyword_matches(text: str, expanded_kws: Set[str]) -> bool:
    """检查文本是否匹配任意一个扩展关键词（子串匹配）。"""
    text_lower = text.lower()
    for kw in expanded_kws:
        if kw.lower() in text_lower:
            return True
    return False


def matches_filters(item: RawTenderItem, keyword: str, region: str,
                     start_date: datetime, end_date: datetime) -> bool:
    """
    三级筛选策略，校验单条信息是否符合用户意图：

    L1「精确匹配」：关键词 + 区域 + 时间 三者均满足
    L2「同义匹配」：扩展同义词后，三者均满足
    L3「宽松匹配」：当关键词无匹配但区域+时间满足且标题/内容不空时，
                   仍保留（避免因同义词覆盖不全而错误丢弃）

    设计考量：
    - 检索阶段（adapter.search）已做了初步筛选，cleaner 的职责是"复验 + 纠偏"
    - L3 的存在是为了防止误删 —— 宁可多保留一条让用户人工判断，
      也好过漏掉一条真正相关的公告
    """
    title_content = (item.title or "") + " " + (item.content or "")

    expanded_kws = _expand_keywords(keyword) if keyword else set()

    # L1: 精确匹配
    l1_kw = keyword and keyword in title_content
    l1_region = region and region in title_content
    l1_time = True
    if item.publish_time:
        l1_time = start_date <= item.publish_time <= end_date

    if l1_kw and l1_region and l1_time:
        return True

    # L2: 同义词匹配
    l2_kw = keyword and _keyword_matches(title_content, expanded_kws)
    if l2_kw and l1_region and l1_time:
        return True

    # L3: 宽松匹配（区域+时间满足即可）
    if l1_region and l1_time and (item.title or item.content):
        return True

    # 如果用户没有指定区域，仅靠关键词和时间判断
    if not region and keyword and l2_kw and l1_time:
        return True

    # 如果关键词、区域都未指定（极端边缘情况），仅靠时间判断
    if not keyword and not region and l1_time:
        return True

    return False


def clean_items(items: List[RawTenderItem], keyword: str, region: str,
                 start_date: datetime, end_date: datetime) -> List[RawTenderItem]:
    """对抓取到的全部条目进行清洗和筛选。"""
    cleaned = []
    stats = {"total": len(items), "noise_filtered": 0, "condition_filtered": 0}

    for item in items:
        # 1. 去除噪声
        original_len = len(item.content)
        item.content = strip_noise(item.content)
        if len(item.content) < original_len * 0.3:
            # 如果去除噪声后内容过短（丢失 >70%），说明原始内容可能本身就是噪声
            stats["noise_filtered"] += 1
            continue

        # 2. 按条件筛选
        if matches_filters(item, keyword, region, start_date, end_date):
            cleaned.append(item)
        else:
            stats["condition_filtered"] += 1

    return cleaned
