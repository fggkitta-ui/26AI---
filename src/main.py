"""
招投标信息智能聚合工具 —— 主入口。

用法：
    # 立即执行（CLI 模式）
    python -m src.main "最近3个月的上海区域内的充电桩招标信息都有哪些"

    # 定时执行
    python -m src.main "最近3个月的上海区域内的充电桩招标信息都有哪些，请汇总后每天9:00发送给我"

    # 演示模式（无需网络，使用内置演示数据验证全流程）
    python -m src.main --demo "最近1个月的安徽省区域内的服务器招标信息都有哪些"

    # 以 Web UI 模式启动
    python -m src.main --web

    # 列出已注册的定时任务
    python -m src.main --list-jobs

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

import argparse
import logging
import sys
import signal
from datetime import datetime
from pathlib import Path

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

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tender-aggregator")

# ---------------------------------------------------------------------------
# 数据源注册
# ---------------------------------------------------------------------------
ADAPTERS = [
    GovPlatformAdapter(),
    LoginRequiredAdapter(),
    AggregatorSiteAdapter(),
]


def run_pipeline(user_query: str, demo_mode: bool = False) -> str:
    """
    执行一次完整的抓取 -> 处理 -> 出文档流程。

    参数：
        user_query: 用户的自然语言问题
        demo_mode: 如果为 True，适配器将使用内置演示数据

    返回：
        生成的 docx 文件路径
    """
    logger.info(f"开始处理查询: {user_query}")

    # 1. 意图解析
    intent = parse_intent(user_query)
    keyword = intent.get("keyword")
    region = intent.get("region")
    time_range = intent.get("time_range")
    schedule = intent.get("schedule", {})

    logger.info(
        f"意图解析结果 —— 关键词: {keyword}, 区域: {region}, "
        f"时间范围: {time_range.get('raw') if time_range else '无'}, "
        f"调度: {schedule.get('raw') or '立即执行'}"
    )

    if not time_range:
        logger.warning("未能解析出时间范围，默认使用最近1个月")
        now = datetime.now()
        time_range = {
            "type": "relative",
            "raw": "最近1个月",
            "start": now.strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"),
        }

    start_date = datetime.strptime(time_range["start"], "%Y-%m-%d")
    end_date = datetime.strptime(time_range["end"], "%Y-%m-%d")

    # 2. 多源抓取
    all_items = []
    for adapter in ADAPTERS:
        try:
            if demo_mode:
                # 强制 demo 模式
                adapter._demo_mode = True
            items = adapter.run(keyword, region, start_date, end_date)
            logger.info(f"[{adapter.source_name}] 抓取到 {len(items)} 条信息")
            all_items.extend(items)
        except Exception as e:
            logger.warning(f"[{adapter.source_name}] 抓取失败: {e}", exc_info=True)

    logger.info(f"共抓取 {len(all_items)} 条原始信息（来自 {len(ADAPTERS)} 个数据源）")

    if not all_items:
        logger.warning(
            "所有数据源均未返回结果。请检查网络连接，或使用 --demo 模式验证全流程。"
        )

    # 3. 清洗
    cleaned = clean_items(all_items, keyword or "", region or "", start_date, end_date)
    logger.info(f"清洗后保留 {len(cleaned)} 条信息（过滤掉 {len(all_items) - len(cleaned)} 条）")

    # 4. 去重
    unique_items = deduplicate(cleaned)
    logger.info(f"去重后保留 {len(unique_items)} 条信息（去除了 {len(cleaned) - len(unique_items)} 条重复）")

    # 5. 增量过滤
    subscription_id = make_subscription_id(user_query)
    pushed_fps = get_pushed_fingerprints(subscription_id)
    new_items = [i for i in unique_items if fingerprint(i) not in pushed_fps]
    logger.info(
        f"增量过滤后保留 {len(new_items)} 条新增信息（历史已推送 {len(pushed_fps)} 条）"
    )

    # 6. 汇总
    summarized = summarize(new_items)
    time_range_desc = f"{time_range['start']} 至 {time_range['end']}（{time_range['raw']}）"

    # 7. 生成 Word 文档
    output_path = build_docx(
        user_query, summarized, time_range_desc,
        is_incremental=bool(pushed_fps),
    )

    # 8. 标记已推送
    mark_as_pushed(subscription_id, [fingerprint(i) for i in new_items])

    logger.info(f"[完成] 已生成文档: {output_path}")
    logger.info(f"   包含 {len(new_items)} 条招投标信息")
    return str(output_path)


def run_web_ui(host: str = "127.0.0.1", port: int = 8080):
    """启动 Web UI 服务。"""
    try:
        from src.web_app import create_app
        app = create_app()
        logger.info(f"启动 Web UI: http://{host}:{port}")
        app.run(host=host, port=port, debug=False)
    except ImportError:
        logger.error(
            "Web UI 依赖未安装，请运行: pip install flask\n"
            "或直接使用 CLI 模式: python -m src.main \"你的查询\""
        )
        sys.exit(1)


def list_jobs():
    """列出已注册的定时任务。"""
    from src.scheduler.state_store import DB_PATH
    import sqlite3

    if not DB_PATH.exists():
        print("暂无已注册的定时任务。")
        return

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT subscription_id, fingerprint, pushed_at FROM pushed_items ORDER BY pushed_at DESC LIMIT 50"
    ).fetchall()
    conn.close()

    if not rows:
        print("暂无已注册的定时任务。")
        return

    print(f"{'订阅ID':<20} {'指纹':<36} {'推送时间'}")
    print("-" * 85)
    for sub_id, fp, pushed_at in rows:
        print(f"{sub_id:<20} {fp:<36} {pushed_at}")


def main():
    parser = argparse.ArgumentParser(
        description="招投标信息智能聚合工具 —— 用自然语言搜索并汇总招投标信息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.main "最近1个月的安徽省区域内的服务器招标信息都有哪些"
  python -m src.main --demo "最近3个月的上海充电桩招标信息"
  python -m src.main --web
  python -m src.main --list-jobs
        """,
    )
    parser.add_argument(
        "query", nargs="?", default=None,
        help="自然语言问题（如: 最近3个月的上海充电桩招标信息都有哪些）",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="演示模式：使用内置演示数据运行全流程（无需网络连接）",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="以 Web UI 模式启动（需安装 flask）",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Web UI 监听地址（默认 127.0.0.1）",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Web UI 监听端口（默认 8080）",
    )
    parser.add_argument(
        "--list-jobs", action="store_true",
        help="列出已注册的定时任务及已推送的历史记录",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="输出详细日志",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --list-jobs
    if args.list_jobs:
        list_jobs()
        return

    # --web
    if args.web:
        run_web_ui(args.host, args.port)
        return

    # CLI 模式
    if not args.query:
        parser.print_help()
        print("\n提示：请提供自然语言查询，例如：")
        print('  python -m src.main "最近1个月的安徽省区域内的服务器招标信息都有哪些"')
        sys.exit(1)

    # 执行意图解析
    intent = parse_intent(args.query)
    schedule = intent.get("schedule", {})
    is_demo = args.demo

    # 打印意图解析结果
    print()
    print("=" * 60)
    print("[意图解析结果]")
    print("-" * 60)
    print(f"  查询语句: {args.query}")
    print(f"  关键词:   {intent.get('keyword') or '未识别'}")
    print(f"  区域:     {intent.get('region') or '未指定'}")
    if intent.get("time_range"):
        tr = intent["time_range"]
        print(f"  时间范围: {tr.get('raw')} ({tr.get('start')} ~ {tr.get('end')})")
    if schedule:
        print(f"  调度方式: {'周期定时' if schedule.get('is_recurring') else '一次性'}")
        if schedule.get("cron"):
            print(f"  Cron:     {schedule['cron']}")
        if schedule.get("run_at") and schedule["run_at"] != "immediate":
            print(f"  执行时间: {schedule['run_at']}")
    print("=" * 60)
    print()

    scheduler = JobScheduler()

    if not schedule.get("is_recurring"):
        if schedule.get("run_at") and schedule["run_at"] != "immediate":
            print(f"[调度] 将于今日 {schedule['run_at']} 执行一次...")
            scheduler.run_once_at(schedule["run_at"], run_pipeline, args.query, is_demo)
            print("调度已注册，等待执行... (按 Ctrl+C 退出)")
            try:
                signal.pause()
            except AttributeError:
                # Windows 不支持 signal.pause()
                import time
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
        else:
            print("[执行] 立即执行...")
            output_path = run_pipeline(args.query, demo_mode=is_demo)
            print(f"\n[输出] 文件: {output_path}")
    else:
        cron = schedule.get("cron", "0 9 * * *")
        print(f"[调度] 已注册周期任务: cron={cron} ({schedule.get('raw', '')})")
        scheduler.schedule_recurring(cron, run_pipeline, args.query, is_demo)

        # 立即执行一次（首次运行）
        print("[执行] 首次执行...")
        run_pipeline(args.query, demo_mode=is_demo)

        print(f"\n调度器运行中，下次执行时间由 cron={cron} 决定。按 Ctrl+C 退出。")
        try:
            signal.pause()
        except AttributeError:
            import time
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n调度器已停止。")

    scheduler.shutdown()


if __name__ == "__main__":
    main()
