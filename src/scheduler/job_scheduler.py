"""
任务调度模块，封装 APScheduler。

- schedule.is_recurring == False -> 立即执行一次（或在 run_at 指定的时间执行一次）
- schedule.is_recurring == True  -> 按 cron 表达式周期性执行，
  每次执行都复用同一个 pipeline，只是通过 state_store 过滤出增量内容
"""

from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


class JobScheduler:
    def __init__(self):
        self._scheduler = BackgroundScheduler()
        self._scheduler.start()

    def run_once_now(self, job_func: Callable, *args, **kwargs) -> None:
        job_func(*args, **kwargs)

    def run_once_at(self, run_at: str, job_func: Callable, *args, **kwargs) -> None:
        """run_at 格式 'HH:MM'，在当天该时间点执行一次。"""
        hh, mm = map(int, run_at.split(":"))
        now = datetime.now()
        run_date = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if run_date < now:
            # 若指定时间已过，视为"立即执行"，避免用户以为任务丢失
            run_date = now
        self._scheduler.add_job(job_func, "date", run_date=run_date, args=args, kwargs=kwargs)

    def schedule_recurring(self, cron_expr: str, job_func: Callable, *args, **kwargs) -> None:
        """cron_expr 格式："分 时 日 月 周"，例如 "0 9 * * *" 表示每天 9:00。"""
        minute, hour, day, month, day_of_week = cron_expr.split()
        trigger = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)
        self._scheduler.add_job(job_func, trigger, args=args, kwargs=kwargs)

    def shutdown(self):
        self._scheduler.shutdown()
