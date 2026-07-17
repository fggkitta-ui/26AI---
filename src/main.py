"""
系统主入口。

用法：
    python -m src.main "最近3个月的上海区域内的充电桩招标信息都有哪些，请汇总后每天9:00发送给我"

流程：
自然语言输入
  -> 意图解析（intent）
  -> 数据源适配层并发抓取（adapters）
  -> 清洗去重（pipeline.cleaner / pipeline.deduplicator）
  -> 汇总生成（pipeline.summarizer）
  -> 增量过滤（scheduler.state_store）
  -> Word 文档生成（document.docx_builder）
  -> 立即执行 或 注册为定时任务（scheduler.job_scheduler）
"""

import sys
from datetime import datetime

from src.intent.rule_parser import parse_intent
from src.adapters.gov_platform_adapter import GovPlatformAdapter
from src.adapters.login_required_adapter import LoginRequiredAdapter
from src.adapters.aggregator_site_adapter import AggregatorSiteAdapter
from src.pipeline.cleaner import clean_items
from src.pipeline.deduplicator import deduplicate, fingerprint
from src.pipeline.summarizer import summarize
from src.scheduler.state_store import get_pushed_fingerprints, mark_as_pushed, make_subscription_id
from src.scheduler.job_scheduler import JobScheduler
from src.document.docx_builder import build_docx

ADAPTERS = [
    GovPlatformAdapter(),
    LoginRequiredAdapter(),
    AggregatorSiteAdapter(),
]


def run_pipeline(user_query: str) -> None:
    """执行一次完整的抓取 -> 处理 -> 出文档流程（供立即执行或定时任务复用）。"""
    intent = parse_intent(user_query)
    keyword = intent["keyword"]
    region = intent["region"]
    time_range = intent["time_range"]
    start_date = datetime.strptime(time_range["start"], "%Y-%m-%d")
    end_date = datetime.strptime(time_range["end"], "%Y-%m-%d")

    all_items = []
    for adapter in ADAPTERS:
        try:
            all_items.extend(adapter.run(keyword, region, start_date, end_date))
        except Exception as e:  # noqa: BLE001
            # 单个数据源失败不应影响其他数据源，记录日志后继续
            print(f"[警告] 数据源 {adapter.source_name} 抓取失败：{e}")

    cleaned = clean_items(all_items, keyword, region, start_date, end_date)
    unique_items = deduplicate(cleaned)

    # 增量过滤：只保留本次订阅未曾推送过的内容
    subscription_id = make_subscription_id(user_query)
    pushed_fps = get_pushed_fingerprints(subscription_id)
    new_items = [i for i in unique_items if fingerprint(i) not in pushed_fps]

    summarized = summarize(new_items)
    time_range_desc = f"{time_range['start']} 至 {time_range['end']}"
    output_path = build_docx(user_query, summarized, time_range_desc,
                              is_incremental=bool(pushed_fps))

    mark_as_pushed(subscription_id, [fingerprint(i) for i in new_items])
    print(f"[完成] 已生成文档：{output_path}")


def main():
    if len(sys.argv) < 2:
        print('用法: python -m src.main "你的自然语言问题"')
        sys.exit(1)

    user_query = sys.argv[1]
    intent = parse_intent(user_query)
    schedule = intent["schedule"]

    scheduler = JobScheduler()
    if not schedule["is_recurring"]:
        if schedule.get("run_at") and schedule["run_at"] != "immediate":
            print(f"[调度] 将于今日 {schedule['run_at']} 执行一次")
            scheduler.run_once_at(schedule["run_at"], run_pipeline, user_query)
        else:
            print("[调度] 未检测到定时需求，立即执行")
            scheduler.run_once_now(run_pipeline, user_query)
    else:
        print(f"[调度] 已注册周期任务，cron = {schedule['cron']}")
        scheduler.schedule_recurring(schedule["cron"], run_pipeline, user_query)
        # 周期任务注册后，通常还需要保持进程存活（如 while True + sleep），
        # 此处省略，Web/CLI 场景下的具体保活方式见 README「运行方式」。


if __name__ == "__main__":
    main()
