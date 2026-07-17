"""
政府/公共资源交易平台适配器示例（免登录数据源）。

TODO：
- 替换 BASE_URL 为实际目标网站
- search()：拼接该网站的列表页检索参数（关键词/地区/日期），解析列表页 HTML
  得到详情页链接
- fetch_detail()：请求详情页，解析标题/发布时间/正文/附件（如为 PDF 附件，
  可结合 pdf 处理库提取文本，便于后续做内容一致性核对）

建议使用 httpx + selectolax/BeautifulSoup 处理静态页面；
若目标站点为前端渲染（Vue/React），改用 Playwright。
"""

from datetime import datetime
from typing import List, Optional

from .base_adapter import BaseAdapter, RawTenderItem

BASE_URL = "https://example-gov-tender-site.gov.cn"  # TODO: 替换为真实网址


class GovPlatformAdapter(BaseAdapter):
    source_name = "示例政府采购公示平台"
    requires_login = False

    def login(self) -> bool:
        # 公开信息无需登录
        return True

    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        # TODO: 实现真实的列表页请求 + 分页遍历 + URL 提取
        raise NotImplementedError("请实现该数据源的列表页检索逻辑")

    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        # TODO: 实现真实的详情页解析逻辑
        raise NotImplementedError("请实现该数据源的详情页解析逻辑")
