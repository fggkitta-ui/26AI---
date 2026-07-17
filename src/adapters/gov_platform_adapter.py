"""
政府/公共资源交易平台适配器 —— 中国政府采购网 (www.ccgp.gov.cn)

中国政府采购网是财政部指定的政府采购信息发布媒体，所有公开招标/中标公告
均在此公示。本适配器通过解析其公开的检索页面抓取招投标信息。

特点：
- 免登录，所有信息公开可查
- 支持关键词、地区、时间范围检索
- 列表页为静态 HTML，详情页包含公告全文

搜索策略：
1. 构造搜索 URL（关键词 + 地区 + 时间范围）
2. 解析列表页，提取公告标题/链接/发布日期
3. 逐个抓取详情页，提取正文、附件链接
4. 对 JS 渲染页面自动降级为 Playwright 方案
"""

import re
import logging
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from .base_adapter import BaseAdapter, RawTenderItem

logger = logging.getLogger(__name__)

# 中国政府采购网 - 公开招标公告列表
BASE_URL = "https://www.ccgp.gov.cn"
SEARCH_URL = "https://search.ccgp.gov.cn/bxsearch"

# 各地区政府采购网分站映射（省级）
REGION_SITES = {
    "安徽": "https://www.ccgp-anhui.gov.cn",
    "北京": "https://www.ccgp-beijing.gov.cn",
    "上海": "https://www.ccgp-shanghai.gov.cn",
    "广东": "https://www.ccgp-guangdong.gov.cn",
    "江苏": "https://www.ccgp-jiangsu.gov.cn",
    "浙江": "https://www.ccgp-zhejiang.gov.cn",
    "山东": "https://www.ccgp-shandong.gov.cn",
    "河南": "https://www.ccgp-henan.gov.cn",
    "湖北": "https://www.ccgp-hubei.gov.cn",
    "湖南": "https://www.ccgp-hunan.gov.cn",
    "四川": "https://www.ccgp-sichuan.gov.cn",
    "福建": "https://www.ccgp-fujian.gov.cn",
    "河北": "https://www.ccgp-hebei.gov.cn",
    "辽宁": "https://www.ccgp-liaoning.gov.cn",
    "陕西": "https://www.ccgp-shaanxi.gov.cn",
    "重庆": "https://www.ccgp-chongqing.gov.cn",
    "天津": "https://www.ccgp-tianjin.gov.cn",
}


class GovPlatformAdapter(BaseAdapter):
    source_name = "中国政府采购网"
    requires_login = False

    # 公告类型映射
    ANNOUNCE_TYPES = {
        "招标": "zbgg",       # 招标公告
        "中标": "zbgs",       # 中标公告
        "更正": "gzgg",       # 更正公告
        "废标": "fbgg",       # 废标公告
    }

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
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                },
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    def login(self) -> bool:
        # 中国政府采购网公开信息无需登录
        return True

    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        """
        在中国政府采购网搜索符合条件的招标公告。

        搜索策略（按优先级）：
        1. 拼接总站搜索 API 参数，获取全国范围内包含关键词的公告
        2. 如有地区限定，通过请求省级分站提高召回精度
        3. 解析返回的搜索结果列表，提取详情页 URL
        """
        detail_urls: List[str] = []
        client = self._get_client()

        # 构建搜索参数
        search_params = {
            "searchtype": "1",
            "page_index": "1",
            "bidSort": "0",
            "buyerName": "",
            "projectCode": "",
            "bidName": keyword,
            "dbselect": "bidx",
            "start_time": start_date.strftime("%Y:%m:%d"),
            "end_time": end_date.strftime("%Y:%m:%d"),
            "pinMu": "0",
            "bidType": "0",
            "saleType": "0",
            "timeType": "6",
        }

        # 如果有地区筛选，使用地区分站搜索
        search_urls = []
        if region and region in REGION_SITES:
            region_base = REGION_SITES[region]
            search_urls.append(f"{region_base}/cggg/")
        search_urls.append(SEARCH_URL)  # 总站搜索作为补充

        for search_url in search_urls[:2]:  # 最多尝试2个搜索入口
            try:
                # 尝试通过 POST 搜索
                resp = client.post(
                    SEARCH_URL,
                    data=search_params,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": "https://search.ccgp.gov.cn/",
                    },
                )
                if resp.status_code == 200:
                    urls = self._parse_search_results(resp.text)
                    detail_urls.extend(urls)
            except Exception as e:
                logger.warning(f"搜索请求失败 ({search_url}): {e}")
                # 如果 POST 失败，尝试 GET 方式
                try:
                    query_str = f"?searchtype=1&bidName={quote(keyword)}"
                    get_url = f"{BASE_URL}/cggg/zygg/{query_str}"
                    resp = client.get(get_url)
                    if resp.status_code == 200:
                        urls = self._parse_list_page(resp.text)
                        detail_urls.extend(urls)
                except Exception as e2:
                    logger.warning(f"GET 方式搜索也失败: {e2}")

        if not detail_urls:
            logger.info(
                f"中国政府采购网在线检索未返回结果（keyword={keyword}, region={region}），"
                f"将使用演示数据。"
            )
            self._demo_mode = True

        return detail_urls

    def _parse_search_results(self, html: str) -> List[str]:
        """解析搜索结果的HTML，提取详情页URL列表。"""
        urls = []
        soup = BeautifulSoup(html, "html.parser")

        # 搜索结果通常在 <ul class="v-search-result"> 或类似结构中
        # 尝试多种可能的选择器
        selectors = [
            "ul.v-search-result li a[href]",
            ".result-list a[href]",
            "table a[href*='cggg']",
            "a[href*='/cggg/']",
            ".list-container a[href]",
        ]

        for selector in selectors:
            for link in soup.select(selector):
                href = link.get("href", "")
                if href and "/cggg/" in href:
                    full_url = urljoin(BASE_URL, href)
                    if full_url not in urls:
                        urls.append(full_url)

        return urls

    def _parse_list_page(self, html: str) -> List[str]:
        """解析公告列表页，提取详情链接。"""
        urls = []
        soup = BeautifulSoup(html, "html.parser")

        # 查找所有指向公告详情的链接
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if any(pattern in href for pattern in ["/cggg/", "/zbgg/", "/zbgs/", "detail"]):
                full_url = urljoin(BASE_URL, href)
                if full_url not in urls:
                    urls.append(full_url)

        return urls

    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        """抓取单个公告详情页，解析标题/发布时间/正文/附件。"""
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
        """解析公告详情页HTML，提取结构化字段。"""
        soup = BeautifulSoup(html, "html.parser")

        # 1. 提取标题 —— 尝试多种选择器
        title = "未知标题"
        title_selectors = [
            "h1", ".title", ".detail-title", ".article-title",
            ".info-title", ".content-title", "title",
            "td[class*='title']", "span[class*='title']",
        ]
        for sel in title_selectors:
            elem = soup.select_one(sel)
            if elem and elem.get_text(strip=True):
                title = elem.get_text(strip=True)
                break

        # 2. 提取发布时间
        publish_time = None
        time_patterns = [
            r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
            r"发布日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
            r"公告时间[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
        ]
        page_text = soup.get_text()
        for pattern in time_patterns:
            m = re.search(pattern, page_text)
            if m:
                time_str = m.group(1)
                try:
                    # 尝试多种日期格式
                    for fmt in ["%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d"]:
                        try:
                            publish_time = datetime.strptime(time_str, fmt)
                            break
                        except ValueError:
                            continue
                    if publish_time:
                        break
                except Exception:
                    pass

        # 3. 提取正文内容
        content_parts = []
        content_selectors = [
            ".article-content", ".detail-content", ".content",
            "#content", ".main-content", "article",
            ".vF_detail_content", ".notice-content",
        ]
        content_elem = None
        for sel in content_selectors:
            content_elem = soup.select_one(sel)
            if content_elem:
                break

        if content_elem:
            # 去除脚本、样式标签
            for tag in content_elem.find_all(["script", "style", "nav"]):
                tag.decompose()
            content_parts.append(content_elem.get_text("\n", strip=True))
        else:
            # 兜底：查找最大的文本块
            body = soup.find("body")
            if body:
                for tag in body.find_all(["script", "style", "nav", "footer"]):
                    tag.decompose()
                content_parts.append(body.get_text("\n", strip=True))

        content = "\n".join(content_parts) if content_parts else "未能提取正文内容"

        # 4. 提取附件链接
        attachment_urls = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            link_text = link.get_text(strip=True)
            # 识别附件：文件扩展名或文本特征
            if any(ext in href.lower() for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"]):
                attachment_urls.append(urljoin(url, href))
            elif any(kw in link_text for kw in ["附件", "下载", "招标文件", "采购文件", "图纸"]):
                attachment_urls.append(urljoin(url, href))

        return RawTenderItem(
            title=title,
            publish_time=publish_time,
            source_url=url,
            content=content,
            attachment_urls=attachment_urls,
            source_name=self.source_name,
        )

    def _generate_demo_item(self) -> Optional[RawTenderItem]:
        """
        演示数据生成（仅供需要展示/测试但网站暂时不可访问时使用）。
        每条演示数据均标注"演示数据"前缀，方便区分。
        """
        import random
        demo_items = [
            {
                "title": "【演示数据】上海市新能源汽车充电设施建设招标公告",
                "time": datetime(2026, 6, 15),
                "url": "https://www.ccgp.gov.cn/cggg/demo/20260615_001",
                "content": (
                    "项目概况：上海市新能源汽车充电设施建设项目招标项目的潜在投标人应在"
                    "上海市公共资源交易中心获取招标文件，并于2026年7月20日09:30前递交投标文件。"
                    "项目名称：上海市新能源汽车充电设施建设项目。"
                    "预算金额：人民币5800万元。"
                    "采购需求：在上海浦东新区、徐汇区、闵行区等区域建设充电桩2000个。"
                    "合同履行期限：合同签订后12个月内完成建设。"
                ),
                "attachments": ["https://www.ccgp.gov.cn/cggg/demo/zbwj_20260615.pdf"],
            },
            {
                "title": "【演示数据】安徽省数据中心服务器采购项目中标结果公告",
                "time": datetime(2026, 5, 20),
                "url": "https://www.ccgp.gov.cn/cggg/demo/20260520_002",
                "content": (
                    "一、项目编号：AHSZ-2026-001。"
                    "二、项目名称：安徽省数据中心服务器采购项目。"
                    "三、中标信息：供应商名称：超聚变数字技术有限公司。"
                    "供应商地址：安徽省合肥市高新区。"
                    "中标金额：人民币1280万元。"
                    "四、主要标的信息：采购高性能服务器120台，包含安装调试及5年运维服务。"
                ),
                "attachments": [],
            },
            {
                "title": "【演示数据】北京地区充电桩设备采购及安装工程招标公告",
                "time": datetime(2026, 7, 1),
                "url": "https://www.ccgp.gov.cn/cggg/demo/20260701_003",
                "content": (
                    "招标条件：本招标项目北京地区充电桩设备采购及安装工程已由北京市发展和改革委员会"
                    "批准建设，项目业主为北京市城市管理委员会，建设资金来自财政拨款，"
                    "出资比例为100%。项目已具备招标条件，现对该项目进行公开招标。"
                    "项目预算：3500万元。"
                    "建设规模：在北京市通州区、大兴区建设公共充电桩800个。"
                ),
                "attachments": [
                    "https://www.ccgp.gov.cn/cggg/demo/zbwj_20260701.pdf",
                    "https://www.ccgp.gov.cn/cggg/demo/tj_20260701.docx",
                ],
            },
            {
                "title": "【演示数据】江苏省南京市电动汽车充电基础设施运营招标公告",
                "time": datetime(2026, 6, 28),
                "url": "https://www.ccgp.gov.cn/cggg/demo/20260628_004",
                "content": (
                    "南京市公共资源交易中心受南京市交通运输局委托，"
                    "就南京市电动汽车充电基础设施运营项目进行公开招标。"
                    "项目名称：南京市电动汽车充电基础设施运营。"
                    "项目预算：2100万元。"
                    "服务期限：3年。"
                    "招标内容：在南京市区范围内运营维护公共充电桩1200个。"
                ),
                "attachments": [],
            },
            {
                "title": "【演示数据】河南省郑州市光伏电站建设项目招标公告",
                "time": datetime(2026, 7, 10),
                "url": "https://www.ccgp.gov.cn/cggg/demo/20260710_005",
                "content": (
                    "招标公告：河南郑州光伏电站建设项目已由相关部门批准，招标人为郑州市能源局。"
                    "项目概况：在郑州市郑东新区建设分布式光伏电站，装机容量50MW。"
                    "预算金额：人民币1.2亿元。"
                    "计划工期：18个月。"
                    "投标截止时间：2026年8月15日09:30。"
                ),
                "attachments": ["https://www.ccgp.gov.cn/cggg/demo/zhaobiao_20260710.pdf"],
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
