"""
需登录招投标网站适配器示例（免费会员账号）。

赛题要求：至少 1 个来源需要登录才能获取信息，仅需注册免费会员、
获取免费会员可见信息即可，无需破解付费墙或使用自动化手段绕过验证码。

TODO：
- 在目标网站手动注册一个免费会员账号，账号/密码建议放到环境变量或
  config/secrets.yaml（务必加入 .gitignore，不要提交到仓库）
- login()：用 Playwright 模拟登录表单提交，成功后把 Cookie/Storage State
  保存到本地文件（例如 data/session_<source>.json），下次直接复用，
  避免频繁触发登录风控
- search()/fetch_detail()：与 gov_platform_adapter 类似，但需要带上登录后的
  Cookie/Session 发起请求
"""

import json
import os
from datetime import datetime
from typing import List, Optional

from .base_adapter import BaseAdapter, RawTenderItem

BASE_URL = "https://example-login-required-tender-site.com"  # TODO: 替换为真实网址
SESSION_FILE = "data/session_login_required.json"


class LoginRequiredAdapter(BaseAdapter):
    source_name = "示例需登录标讯网站（免费会员）"
    requires_login = True

    def login(self) -> bool:
        if os.path.exists(SESSION_FILE):
            # 已有登录态缓存，直接复用（建议加过期时间校验）
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                self._session_state = json.load(f)
            return True

        # TODO: 使用 Playwright 打开登录页 -> 填写账号密码（从环境变量读取）
        #       -> 提交 -> 等待跳转成功 -> context.storage_state(path=SESSION_FILE)
        #
        # 示例伪代码：
        # from playwright.sync_api import sync_playwright
        # with sync_playwright() as p:
        #     browser = p.chromium.launch()
        #     context = browser.new_context()
        #     page = context.new_page()
        #     page.goto(f"{BASE_URL}/login")
        #     page.fill("#username", os.environ["TENDER_SITE_USER"])
        #     page.fill("#password", os.environ["TENDER_SITE_PASS"])
        #     page.click("#login-btn")
        #     page.wait_for_selector(".user-avatar")
        #     context.storage_state(path=SESSION_FILE)
        raise NotImplementedError("请实现真实登录逻辑并保存登录态")

    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        # TODO: 带上登录态发起检索请求，只抓取免费会员可见的列表条目
        raise NotImplementedError("请实现该数据源的列表页检索逻辑")

    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        # TODO: 带上登录态请求详情页；若遇到"需升级会员查看"的内容块，
        #       应跳过该字段而不是报错，只汇总免费会员实际可见的部分
        raise NotImplementedError("请实现该数据源的详情页解析逻辑")
