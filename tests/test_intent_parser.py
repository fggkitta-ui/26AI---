"""
意图解析模块的单元测试。
运行：pytest tests/test_intent_parser.py -v
"""

from datetime import datetime
from src.intent.rule_parser import parse_intent


FIXED_NOW = datetime(2026, 7, 17)


def test_relative_time_and_immediate_schedule():
    result = parse_intent("最近1个月的安徽省区域内的服务器招标信息都有哪些", now=FIXED_NOW)
    assert result["region"] == "安徽"
    assert result["keyword"] == "服务器"
    assert result["time_range"]["type"] == "relative"
    assert result["schedule"]["is_recurring"] is False


def test_absolute_month_and_daily_schedule():
    query = "最近3个月的上海区域内的充电桩招标信息都有哪些，请汇总后每天9:00发送给我"
    result = parse_intent(query, now=FIXED_NOW)
    assert result["region"] == "上海"
    assert result["keyword"] == "充电桩"
    assert result["schedule"]["is_recurring"] is True
    assert result["schedule"]["cron"] == "0 9 * * *"


def test_generalization_on_unseen_phrasing():
    """验证泛化能力：这个问法没有出现在赛题示例里。"""
    query = "最近2周河南省的光伏电站招标信息都有哪些，请每周一9:00发给我"
    result = parse_intent(query, now=FIXED_NOW)
    assert result["region"] == "河南"
    assert result["keyword"] == "光伏电站"
    assert result["schedule"]["cron"] == "0 9 * * 1"
