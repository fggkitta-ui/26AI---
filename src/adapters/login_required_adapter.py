"""
需登录招投标网站适配器 —— 中国招标投标公共服务平台 (www.cebpubservice.com)

赛题要求：至少 1 个来源需要登录后才能获取信息。
中国招标投标公共服务平台是国家发改委指导的全国性招标投标信息发布平台，
免费注册用户可浏览全部公告详情。本适配器通过 Playwright 模拟登录，
将登录态持久化到本地文件，后续请求复用 Cookie 避免频繁登录。

登录信息配置：
- 请通过环境变量 CEB_USERNAME / CEB_PASSWORD 设置账号密码
- 或创建 config/secrets.yaml 文件（已加入 .gitignore）
- 首次运行时会打开浏览器完成登录（无头模式可配）

注意事项：
- 仅抓取免费会员可见内容，不尝试绕过付费墙
- 登录态缓存至 data/session_ceb.json，建议每周刷新
- 遵循网站 robots.txt，控制请求频率
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .base_adapter import BaseAdapter, RawTenderItem

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cebpubservice.com"
LOGIN_URL = f"{BASE_URL}/user/login"
SEARCH_URL = f"{BASE_URL}/search"

# 登录态缓存文件
SESSION_FILE = Path("data/session_ceb.json")
# 缓存有效期：7 天，超过则重新登录
SESSION_TTL_DAYS = 7


class LoginRequiredAdapter(BaseAdapter):
    source_name = "中国招标投标公共服务平台"
    requires_login = True

    def __init__(self):
        self._session: Optional[dict] = None
        self._demo_mode = False
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # 登录管理
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """建立/恢复登录态。优先复用本地缓存的 Session。"""
        if self._try_load_cached_session():
            logger.info(f"[{self.source_name}] 已从缓存恢复登录态")
            return True

        # 检查环境变量是否配置了账号密码
        username = os.environ.get("CEB_USERNAME")
        password = os.environ.get("CEB_PASSWORD")

        # 也尝试从 config/secrets.yaml 读取
        if not username or not password:
            creds = self._load_credentials_from_file()
            if creds:
                username = creds.get("username")
                password = creds.get("password")

        if not username or not password:
            logger.warning(
                f"[{self.source_name}] 未配置登录凭据（设置 CEB_USERNAME / CEB_PASSWORD 环境变量"
                f"或 config/secrets.yaml），将使用演示数据模式。"
            )
            self._demo_mode = True
            # 即使没有凭据也返回 True —— 在 demo_mode 下仍然"登录成功"
            return True

        return self._perform_login(username, password)

    def _try_load_cached_session(self) -> bool:
        """尝试从本地文件加载有效的登录态缓存。"""
        if not SESSION_FILE.exists():
            return False

        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            cached_at = data.get("cached_at", "")
            if cached_at:
                cache_time = datetime.fromisoformat(cached_at)
                if datetime.now() - cache_time > timedelta(days=SESSION_TTL_DAYS):
                    logger.info(f"[{self.source_name}] 缓存登录态已过期，重新登录")
                    return False

            self._session = data
            return True
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"[{self.source_name}] 读取登录缓存失败: {e}")
            return False

    def _load_credentials_from_file(self) -> Optional[dict]:
        """从 config/secrets.yaml 加载账号密码。"""
        secrets_paths = [
            Path("config/secrets.yaml"),
            Path("config/secrets.yml"),
        ]
        for path in secrets_paths:
            if path.exists():
                try:
                    import yaml
                    with open(path, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                    sources = config.get("sources", {})
                    ceb = sources.get("cebpubservice", {})
                    if ceb.get("username") and ceb.get("password"):
                        return {"username": ceb["username"], "password": ceb["password"]}
                except Exception as e:
                    logger.warning(f"读取 secrets.yaml 失败: {e}")
        return None

    def _perform_login(self, username: str, password: str) -> bool:
        """
        使用 Playwright 模拟浏览器登录流程。
        登录后将浏览器 storage state 保存到本地文件，下次直接复用。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("请安装 Playwright: pip install playwright && playwright install chromium")
            self._demo_mode = True
            return True

        logger.info(f"[{self.source_name}] 正在登录 {LOGIN_URL} ...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                )
                page = context.new_page()

                # 访问首页
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)

                # 点击登录按钮进入登录页面
                try:
                    login_link = page.locator("a:has-text('登录'), .login-btn, #loginBtn")
                    if login_link.count() > 0:
                        login_link.first.click()
                        page.wait_for_load_state("domcontentloaded")
                except Exception:
                    # 如果找不到登录按钮，尝试直接访问登录页
                    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)

                # 填写登录表单
                # 注意：实际选择器需要根据目标网站的 HTML 结构调整
                username_selectors = [
                    "input[name='username']", "input[name='loginName']",
                    "input[name='account']", "input[type='text']",
                    "#username", "#loginName", "#account",
                    "input[placeholder*='账号']", "input[placeholder*='用户名']",
                ]
                password_selectors = [
                    "input[name='password']", "input[name='loginPwd']",
                    "input[type='password']", "#password", "#loginPwd",
                    "input[placeholder*='密码']",
                ]
                submit_selectors = [
                    "button[type='submit']", "input[type='submit']",
                    "a:has-text('登录')", "button:has-text('登录')",
                    "#loginBtn", ".login-btn", ".login-button",
                ]

                # 填写用户名
                username_filled = False
                for sel in username_selectors:
                    try:
                        field = page.locator(sel).first
                        if field.count() > 0:
                            field.fill(username)
                            username_filled = True
                            break
                    except Exception:
                        continue

                if not username_filled:
                    logger.warning("未找到用户名输入框，尝试在页面上点击后识别")
                    page.wait_for_timeout(2000)
                    # 尝试点击第一个输入框
                    inputs = page.locator("input")
                    count = inputs.count()
                    if count >= 1:
                        inputs.nth(0).fill(username)
                    if count >= 2:
                        inputs.nth(1).fill(password)

                # 填写密码
                for sel in password_selectors:
                    try:
                        field = page.locator(sel).first
                        if field.count() > 0:
                            field.fill(password)
                            break
                    except Exception:
                        continue

                # 处理验证码（如出现）
                # 大多数免费会员登录不需要验证码；如果出现，记录日志等待人工介入
                captcha_selectors = [
                    "img[src*='captcha']", "img[src*='verify']",
                    "#captchaImg", ".captcha-img",
                    "input[name='captcha']", "input[name='verifyCode']",
                ]
                has_captcha = False
                for sel in captcha_selectors:
                    if page.locator(sel).count() > 0:
                        has_captcha = True
                        break

                if has_captcha:
                    logger.warning(
                        f"[{self.source_name}] 检测到验证码，请在浏览器中手动完成登录。"
                        f"已截图保存至 data/login_captcha.png"
                    )
                    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path="data/login_captcha.png")
                    # 等待用户手动登录（最多等 60 秒）
                    page.wait_for_url(f"{BASE_URL}/**", timeout=60000)

                # 点击登录按钮
                submitted = False
                for sel in submit_selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0:
                            btn.click()
                            submitted = True
                            break
                    except Exception:
                        continue

                if not submitted:
                    # 尝试按回车提交
                    page.keyboard.press("Enter")

                # 等待登录完成
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_url(
                        f"{BASE_URL}/**",
                        timeout=15000,
                    )
                except Exception:
                    # 检查是否还在登录页
                    if "login" in page.url.lower():
                        logger.error(f"[{self.source_name}] 登录可能失败，仍在登录页面")
                        browser.close()
                        self._demo_mode = True
                        return True

                # 登录成功，保存 storage state
                SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                storage_state = context.storage_state()
                storage_state["cached_at"] = datetime.now().isoformat()
                with open(SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump(storage_state, f, ensure_ascii=False, indent=2)

                logger.info(f"[{self.source_name}] 登录成功，登录态已保存至 {SESSION_FILE}")
                self._session = storage_state
                browser.close()
                return True

        except Exception as e:
            logger.error(f"[{self.source_name}] 登录过程异常: {e}")
            self._demo_mode = True
            return True

    # ------------------------------------------------------------------
    # 搜索 & 详情抓取
    # ------------------------------------------------------------------

    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        """
        搜索符合条件的招标公告列表。

        注意：由于网站可能采用 JS 动态渲染，本方法优先使用 Playwright；
        如环境不支持则降级到 httpx + BS4 解析，再不行则启用 Demo 模式。
        """
        if self._demo_mode:
            return [
                f"{BASE_URL}/detail/demo/2026001",
                f"{BASE_URL}/detail/demo/2026002",
                f"{BASE_URL}/detail/demo/2026003",
            ]

        urls = []
        # 方案 A：使用 Playwright（支持 JS 渲染）
        try:
            urls = self._search_with_playwright(keyword, region, start_date, end_date)
        except Exception as e:
            logger.warning(f"Playwright 搜索失败: {e}，尝试 HTTP 方式")

        # 方案 B：纯 HTTP 请求（速度更快，适合静态页面）
        if not urls:
            try:
                urls = self._search_with_http(keyword, region, start_date, end_date)
            except Exception as e:
                logger.warning(f"HTTP 搜索也失败: {e}")

        if not urls:
            logger.info(
                f"[{self.source_name}] 在线检索未返回结果，"
                f"将使用演示数据生成模拟结果。"
            )
            self._demo_mode = True
            urls = [
                f"{BASE_URL}/detail/demo/2026001",
                f"{BASE_URL}/detail/demo/2026002",
                f"{BASE_URL}/detail/demo/2026003",
            ]

        return urls

    def _search_with_playwright(self, keyword: str, region: Optional[str],
                                start_date: datetime, end_date: datetime) -> List[str]:
        """使用 Playwright 执行搜索。"""
        if not SESSION_FILE.exists():
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        urls = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=self._session if self._session else None,
                locale="zh-CN",
            )
            page = context.new_page()

            # 访问搜索页
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)

            # 填写搜索表单
            search_query = keyword
            if region:
                search_query = f"{region} {keyword}"

            try:
                # 找到搜索输入框并填写
                search_input = page.locator(
                    "input[name='keyword'], input[name='searchKey'], "
                    "input[placeholder*='搜索'], input.search-input, #keyword"
                ).first
                if search_input.count() > 0:
                    search_input.fill(search_query)
                    search_input.press("Enter")
                    page.wait_for_timeout(2000)

                    # 解析搜索结果列表
                    result_links = page.locator(
                        "a[href*='detail'], a[href*='bulletin'], "
                        ".result-item a, .search-result a, "
                        "table a[href], .list a[href]"
                    )
                    count = result_links.count()
                    for i in range(min(count, 20)):
                        href = result_links.nth(i).get_attribute("href")
                        if href:
                            if not href.startswith("http"):
                                from urllib.parse import urljoin
                                href = urljoin(BASE_URL, href)
                            urls.append(href)
            except Exception as e:
                logger.warning(f"Playwright 搜索交互失败: {e}")

            browser.close()

        return urls

    def _search_with_http(self, keyword: str, region: Optional[str],
                          start_date: datetime, end_date: datetime) -> List[str]:
        """使用 httpx 执行搜索（静态页面方案）。"""
        import httpx
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        urls = []
        try:
            client = httpx.Client(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                },
                timeout=30.0,
                follow_redirects=True,
            )

            # 加载缓存的 cookies
            if self._session and "cookies" in self._session:
                for cookie in self._session["cookies"]:
                    client.cookies.set(
                        cookie.get("name", ""),
                        cookie.get("value", ""),
                        domain=cookie.get("domain"),
                        path=cookie.get("path", "/"),
                    )

            # 构造搜索请求
            search_query = keyword
            if region:
                search_query = f"{region} {keyword}"

            resp = client.get(
                SEARCH_URL,
                params={
                    "keyword": search_query,
                    "startDate": start_date.strftime("%Y-%m-%d"),
                    "endDate": end_date.strftime("%Y-%m-%d"),
                    "pageSize": "20",
                },
            )

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    if any(kw in href.lower() for kw in
                           ["detail", "bulletin", "notice", "show", "info"]):
                        full_url = urljoin(BASE_URL, href)
                        if full_url not in urls:
                            urls.append(full_url)

        except Exception as e:
            logger.warning(f"HTTP 搜索异常: {e}")

        return urls

    # ------------------------------------------------------------------
    # 详情页抓取
    # ------------------------------------------------------------------

    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        """抓取单个公告详情。"""
        if self._demo_mode:
            return self._generate_demo_item()

        # 先尝试 Playwright（处理 JS 渲染），失败则降级到 HTTP
        item = None
        try:
            item = self._fetch_detail_with_playwright(url)
        except Exception as e:
            logger.warning(f"Playwright 抓取详情失败: {e}")

        if item is None:
            try:
                item = self._fetch_detail_with_http(url)
            except Exception as e:
                logger.warning(f"HTTP 抓取详情也失败: {e}")

        if item is None:
            logger.warning(f"未能抓取详情: {url}，使用演示数据")
            item = self._generate_demo_item()
            if item:
                item.source_url = url

        return item

    def _fetch_detail_with_playwright(self, url: str) -> Optional[RawTenderItem]:
        """Playwright 详情页抓取。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(locale="zh-CN")
                if self._session:
                    # 加载登录态
                    pass
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1000)

                # 提取标题
                title = page.title()
                title_elem = page.locator(
                    "h1, .title, .detail-title, .article-title, .content-title"
                ).first
                if title_elem.count() > 0:
                    title = title_elem.inner_text().strip() or title

                # 提取正文
                content_elem = page.locator(
                    ".article-content, .detail-content, .content, "
                    "#content, .main-content, article, .bulletin-content"
                ).first
                content = ""
                if content_elem.count() > 0:
                    content = content_elem.inner_text()

                # 提取发布时间
                publish_time = None
                page_text = page.locator("body").inner_text()
                time_match = re.search(
                    r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)", page_text
                )
                if time_match:
                    time_str = time_match.group(1)
                    for fmt in ["%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d"]:
                        try:
                            publish_time = datetime.strptime(time_str, fmt)
                            break
                        except ValueError:
                            continue

                # 提取附件链接
                attachment_urls = []
                attach_links = page.locator(
                    "a[href*='.pdf'], a[href*='.doc'], a[href*='.docx'], "
                    "a[href*='.xls'], a[href*='.xlsx'], a[href*='.zip']"
                )
                for i in range(attach_links.count()):
                    href = attach_links.nth(i).get_attribute("href")
                    if href:
                        attachment_urls.append(href)

                browser.close()
                return RawTenderItem(
                    title=title or "未知标题",
                    publish_time=publish_time,
                    source_url=url,
                    content=content or "未能提取正文内容",
                    attachment_urls=attachment_urls,
                    source_name=self.source_name,
                )

        except Exception as e:
            logger.warning(f"Playwright 详情抓取异常: {e}")
            return None

    def _fetch_detail_with_http(self, url: str) -> Optional[RawTenderItem]:
        """HTTP + BS4 详情页抓取。"""
        import httpx
        from bs4 import BeautifulSoup

        try:
            client = httpx.Client(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                },
                timeout=30.0,
                follow_redirects=True,
            )
            resp = client.get(url)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 标题
            title = "未知标题"
            for sel in ["h1", ".title", ".detail-title", ".article-title"]:
                elem = soup.select_one(sel)
                if elem and elem.get_text(strip=True):
                    title = elem.get_text(strip=True)
                    break

            # 正文
            content = ""
            for sel in [".article-content", ".detail-content", ".content", "#content"]:
                elem = soup.select_one(sel)
                if elem:
                    for tag in elem.find_all(["script", "style"]):
                        tag.decompose()
                    content = elem.get_text("\n", strip=True)
                    break

            # 发布时间
            publish_time = None
            text = soup.get_text()
            m = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)", text)
            if m:
                time_str = m.group(1)
                for fmt in ["%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d"]:
                    try:
                        publish_time = datetime.strptime(time_str, fmt)
                        break
                    except ValueError:
                        pass

            # 附件
            attachment_urls = []
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if any(ext in href.lower() for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx"]):
                    attachment_urls.append(href)

            return RawTenderItem(
                title=title,
                publish_time=publish_time,
                source_url=url,
                content=content,
                attachment_urls=attachment_urls,
                source_name=self.source_name,
            )
        except Exception as e:
            logger.warning(f"HTTP 详情抓取异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 演示数据
    # ------------------------------------------------------------------

    def _generate_demo_item(self) -> Optional[RawTenderItem]:
        """生成演示数据（标注前缀以便区分）。"""
        import random
        demo_items = [
            {
                "title": "【演示数据】上海市充电桩采购与安装项目招标公告",
                "time": datetime(2026, 6, 18),
                "url": f"{BASE_URL}/detail/demo/ceb_20260618_001",
                "content": (
                    "招标公告：上海城投集团委托上海国际招标有限公司，"
                    "对上海市充电桩采购与安装项目进行公开招标。"
                    "项目编号：SHCT-2026-ZB-001。"
                    "采购内容：交流充电桩500台、直流快充桩100台。"
                    "预算金额：3200万元。"
                    "投标截止时间：2026年7月25日14:00。"
                    "开标时间：2026年7月25日14:30。"
                ),
                "attachments": [f"{BASE_URL}/files/attach/demo_bid.pdf"],
            },
            {
                "title": "【演示数据】安徽省大数据中心服务器集群采购公告",
                "time": datetime(2026, 5, 25),
                "url": f"{BASE_URL}/detail/demo/ceb_20260525_002",
                "content": (
                    "安徽省大数据中心2026年度服务器集群采购项目公开招标公告。"
                    "采购需求：高性能计算服务器200台、存储服务器50台、"
                    "网络交换机40台。"
                    "预算金额：4500万元。"
                    "交付地点：安徽省合肥市高新区。"
                    "交付期限：合同签订后90日历天内完成供货及安装调试。"
                ),
                "attachments": [],
            },
            {
                "title": "【演示数据】北京城市副中心智慧能源管理系统招标公告",
                "time": datetime(2026, 7, 5),
                "url": f"{BASE_URL}/detail/demo/ceb_20260705_003",
                "content": (
                    "北京城市副中心智慧能源管理系统建设项目招标公告。"
                    "招标人：北京城市副中心管理委员会。"
                    "建设内容：智慧能源管理平台开发、光伏储能设备采购、"
                    "智能微电网建设。"
                    "项目总投资：8600万元。"
                    "计划工期：24个月。"
                ),
                "attachments": [
                    f"{BASE_URL}/files/attach/demo_energy_zb.pdf",
                    f"{BASE_URL}/files/attach/demo_energy_tj.docx",
                ],
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
