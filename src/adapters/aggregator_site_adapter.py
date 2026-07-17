"""
行业协会 / 商业聚合网站适配器 —— 千里马招标网 (www.qianlima.com)

千里马招标网是国内较大的招投标商业信息聚合平台，收录了来自全国各地
政府采购网、公共资源交易平台的招标/中标公告。本适配器从该平台抓取
聚合信息，为跨站去重提供对比素材（聚合站的公告常转载政府原始公告）。

特点：
- 商业聚合站，部分信息免登录可见
- 支持关键词、地区、行业筛选
- 搜索结果包含政府原始来源链接，方便追溯
- 列表页与详情页均为服务端渲染，httpx + BS4 即可处理

注意事项：
- 聚合站上的信息可能与政府原始平台重复，这正是去重模块存在的意义
- 仅抓取公开可见的摘要和列表信息
- 遵守网站 robots.txt
"""

import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from .base_adapter import BaseAdapter, RawTenderItem

logger = logging.getLogger(__name__)

BASE_URL = "https://www.qianlima.com"
SEARCH_URL = "https://search.qianlima.com"


class AggregatorSiteAdapter(BaseAdapter):
    source_name = "千里马招标网（行业聚合平台）"
    requires_login = False

    def __init__(self):
        self._client: Optional[httpx.Client] = None
        self._demo_mode = False

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    def login(self) -> bool:
        # 聚合站的部分信息免登录可见
        return True

    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        """
        在聚合站搜索符合条件的招标公告。

        搜索策略：
        1. 构造搜索 URL（关键词 + 地区 + 时间）
        2. 请求列表页，解析 HTML 提取详情页链接
        3. 遍历搜索结果分页（最多 3 页，控制请求量）
        4. 失败则启用演示数据模式
        """
        client = self._get_client()
        detail_urls: List[str] = []

        # 构造搜索查询词
        search_keyword = keyword
        if region:
            search_keyword = f"{region} {keyword}"

        search_urls_to_try = [
            # 各种可能的搜索入口
            f"{BASE_URL}/search?kw={quote(search_keyword)}",
            f"{BASE_URL}/index/search?keyword={quote(search_keyword)}",
            f"{BASE_URL}/zbgg/search?q={quote(search_keyword)}",
            f"https://search.qianlima.com/search?keyword={quote(search_keyword)}",
        ]

        for search_url in search_urls_to_try[:2]:  # 最多尝试 2 个
            try:
                resp = client.get(search_url)
                if resp.status_code == 200:
                    urls = self._parse_search_results(resp.text)
                    detail_urls.extend(urls)
                    if detail_urls:
                        break
            except Exception as e:
                logger.warning(f"搜索请求失败 ({search_url}): {e}")

        # 如果直接搜索没有结果，尝试首页列表
        if not detail_urls:
            try:
                resp = client.get(f"{BASE_URL}/")
                if resp.status_code == 200:
                    urls = self._parse_search_results(resp.text)
                    detail_urls.extend(urls)
            except Exception as e:
                logger.warning(f"首页请求失败: {e}")

        if not detail_urls:
            logger.info(
                f"[{self.source_name}] 在线检索未返回结果（kw={keyword}, region={region}），"
                f"将使用演示数据。"
            )
            self._demo_mode = True

        return detail_urls

    def _parse_search_results(self, html: str) -> List[str]:
        """解析搜索结果 HTML，提取详情页链接。"""
        urls = []
        soup = BeautifulSoup(html, "html.parser")

        # 搜索结果的常见 HTML 结构
        selectors = [
            ".search-result a[href]", ".result-list a[href]",
            ".list-item a[href]", "a[href*='detail']",
            "a[href*='zbgg']", "a[href*='detail/']",
            ".tender-list a[href]", "table a[href*='show']",
            ".news-list a[href]", ".article-list a[href]",
        ]

        for selector in selectors:
            try:
                for link in soup.select(selector):
                    href = link.get("href", "")
                    if href and not href.startswith("#") and not href.startswith("javascript"):
                        full_url = urljoin(BASE_URL, href)
                        if full_url not in urls:
                            urls.append(full_url)
            except Exception:
                continue

        # 限制数量，避免请求过多
        return urls[:20]

    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        """抓取单个详情页。"""
        if self._demo_mode:
            return self._generate_demo_item()

        client = self._get_client()
        try:
            resp = client.get(url)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                logger.warning(f"详情页请求失败 {url}: HTTP {resp.status_code}")
                return None
            return self._parse_detail_page(resp.text, url)
        except Exception as e:
            logger.warning(f"抓取详情页失败 {url}: {e}")
            return None

    def _parse_detail_page(self, html: str, url: str) -> Optional[RawTenderItem]:
        """解析详情页 HTML。"""
        soup = BeautifulSoup(html, "html.parser")

        # 标题
        title = "未知标题"
        title_selectors = [
            "h1", ".title", ".detail-title", ".article-title",
            "td[class*='title']", ".news-title", ".info-title",
            "meta[property='og:title']",
        ]
        for sel in title_selectors:
            elem = soup.select_one(sel)
            if elem:
                if sel.startswith("meta"):
                    title = elem.get("content", "")
                else:
                    title = elem.get_text(strip=True)
                if title:
                    break

        # 发布时间
        publish_time = None
        page_text = soup.get_text()
        time_patterns = [
            r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"(\d{4}年\d{1,2}月\d{1,2}日)",
            r"时间[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"发布日期[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        ]
        for pattern in time_patterns:
            m = re.search(pattern, page_text)
            if m:
                time_str = m.group(1)
                for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
                    try:
                        publish_time = datetime.strptime(time_str, fmt)
                        break
                    except ValueError:
                        continue
                if publish_time:
                    break

        # 正文
        content = ""
        content_selectors = [
            ".article-content", ".detail-content", ".content",
            "#content", ".news-content", ".main-content",
            "article", ".detail-text", ".info-content",
        ]
        for sel in content_selectors:
            content_elem = soup.select_one(sel)
            if content_elem:
                for tag in content_elem.find_all(["script", "style", "nav"]):
                    tag.decompose()
                content = content_elem.get_text("\n", strip=True)
                if content:
                    break

        if not content:
            # 兜底
            body = soup.find("body")
            if body:
                for tag in body.find_all(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                content = body.get_text("\n", strip=True)

        # 附件链接
        attachment_urls = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if any(ext in href.lower() for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"]):
                attachment_urls.append(urljoin(url, href))

        # 检查是否指向原始政府公告（去重时需要）
        # 聚合站通常会在文章中注明"来源：XXX政府采购网"
        source_ref = ""
        source_match = re.search(r"来源[：:]\s*(.{2,30})", soup.get_text())
        if source_match:
            source_ref = source_match.group(1).strip()

        return RawTenderItem(
            title=title,
            publish_time=publish_time,
            source_url=url,
            content=content,
            attachment_urls=attachment_urls,
            source_name=f"{self.source_name}" + (f" | 原始来源：{source_ref}" if source_ref else ""),
        )

    def _generate_demo_item(self) -> Optional[RawTenderItem]:
        """生成演示数据。"""
        import random
        demo_items = [
            {
                "title": "【演示数据】上海浦东新区公共充电桩建设项目中标候选人公示",
                "time": datetime(2026, 7, 12),
                "url": f"{BASE_URL}/detail/demo/ql_20260712_001",
                "content": (
                    "上海浦东新区公共充电桩建设项目（招标编号：SHPD-2026-018）"
                    "于2026年7月10日开标，经评标委员会评审，现将中标候选人公示如下："
                    "第一中标候选人：上海电力新能源有限公司，投标报价：2850万元；"
                    "第二中标候选人：万邦新能源科技有限公司，投标报价：2910万元；"
                    "第三中标候选人：星星充电科技有限公司，投标报价：2960万元。"
                    "公示期：2026年7月12日至2026年7月15日。"
                    "来源：上海市公共资源交易中心。"
                ),
                "attachments": [],
            },
            {
                "title": "【演示数据】安徽省合肥市政务云平台扩容服务器采购招标",
                "time": datetime(2026, 6, 20),
                "url": f"{BASE_URL}/detail/demo/ql_20260620_002",
                "content": (
                    "合肥市数据资源局政务云平台扩容项目公开招标公告。"
                    "采购内容：GPU服务器50台、存储节点30台、万兆交换机20台。"
                    "预算金额：3900万元。"
                    "获取招标文件时间：2026年6月20日至6月27日。"
                    "投标截止时间：2026年7月11日09:30。"
                    "来源：安徽合肥公共资源交易中心。"
                ),
                "attachments": [f"{BASE_URL}/file/demo/hf_zb.pdf"],
            },
            {
                "title": "【演示数据】浙江省杭州市分布式光伏发电项目EPC总承包招标",
                "time": datetime(2026, 7, 3),
                "url": f"{BASE_URL}/detail/demo/ql_20260703_003",
                "content": (
                    "杭州市分布式光伏发电项目（一期）EPC总承包招标公告。"
                    "招标人：杭州市能源集团有限公司。"
                    "建设地点：杭州市余杭区、萧山区。"
                    "建设规模：分布式光伏总装机容量30MW。"
                    "项目总投资：1.1亿元。"
                    "计划工期：240日历天。"
                    "来源：浙江省公共资源交易中心。"
                ),
                "attachments": [],
            },
        ]
        chosen = random.choice(demo_items)
        return RawTenderItem(
            title=chosen["title"],
            publish_time=chosen["time"],
            source_url=chosen["url"],
            content=chosen["content"],
            attachment_urls=chosen["attachments"],
            source_name=self.source_name,
        )
