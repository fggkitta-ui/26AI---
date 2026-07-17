"""
数据源适配器抽象基类。

设计目的：
- 每个招投标信息网站封装成一个独立的 Adapter 子类，互不影响；
- 新增数据源时只需新建一个文件、实现下面 3 个方法，无需改动主流程；
- 统一返回结构，方便清洗/去重/汇总模块以同一种数据结构处理多来源数据。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class RawTenderItem:
    """单条抓取到的原始招投标信息，字段对应赛题要求的汇总五要素。"""

    title: str
    publish_time: Optional[datetime]
    source_url: str
    content: str                     # 清洗前的正文内容
    attachment_urls: List[str] = field(default_factory=list)
    source_name: str = ""            # 数据源站点名称，便于去重时标注来源


class BaseAdapter(ABC):
    """所有网站适配器的统一接口。"""

    #: 数据源展示名称，子类需覆盖
    source_name: str = "unnamed_source"

    #: 是否需要登录态才能获取有效信息
    requires_login: bool = False

    @abstractmethod
    def login(self) -> bool:
        """
        建立/恢复登录态（如需要）。
        不需要登录的数据源可直接 return True。
        建议实现：Cookie 持久化到本地文件，避免每次都重新登录。
        """
        raise NotImplementedError

    @abstractmethod
    def search(self, keyword: str, region: Optional[str],
               start_date: datetime, end_date: datetime) -> List[str]:
        """
        根据关键词/地域/时间范围，在列表页检索出符合条件的详情页 URL 列表。
        返回详情页 URL 列表（不在这一步抓取正文，减少无效抓取）。
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_detail(self, url: str) -> Optional[RawTenderItem]:
        """
        抓取单个详情页，解析出标题/发布时间/正文/附件链接。
        解析失败返回 None，由上层跳过该条目并记录日志，不中断整体流程。
        """
        raise NotImplementedError

    def run(self, keyword: str, region: Optional[str],
            start_date: datetime, end_date: datetime) -> List[RawTenderItem]:
        """默认执行流程：login -> search -> fetch_detail，子类一般无需覆盖。"""
        if self.requires_login and not self.login():
            raise RuntimeError(f"[{self.source_name}] 登录失败，跳过该数据源")

        urls = self.search(keyword, region, start_date, end_date)
        items = []
        for url in urls:
            item = self.fetch_detail(url)
            if item is not None:
                items.append(item)
        return items
