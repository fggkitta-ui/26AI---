"""
行业协会 / 商业聚合网站适配器示例（第三个数据源，凑齐 >=2 个来源的要求，
同时提供跨站去重的素材 —— 商业聚合站常常转载政府平台的原始公告）。

TODO：实现方式与 gov_platform_adapter 类似，注意标注 source_name 以便
后续去重模块识别"这条内容可能是另一个来源的转载"。
"""

from datetime import datetime
from typing import List, Optional

from .base_adapter import BaseAdapter, RawTenderItem

BASE_URL = "https://example-aggregator-site.com"  # TODO: 替换为真实网址


class AggregatorSiteAdapter(BaseAdapter):
    source_name = "示例行业聚合站点"
    requires_login = False

    def login(self) -> bool:
        return True

    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        raise NotImplementedError("请实现该数据源的列表页检索逻辑")

    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        raise NotImplementedError("请实现该数据源的详情页解析逻辑")
