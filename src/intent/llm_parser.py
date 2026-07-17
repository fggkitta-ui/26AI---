"""
意图解析模块 —— LLM 结构化抽取版本（生产环境推荐方案）

用途：
- rule-based 版本（intent_parser.py）覆盖题目给出的常规问法，速度快、零成本，
  但面对更灵活的长尾自然语言表达（口语化、多重从句、隐含时间表达等）时
  泛化能力有限。
- 本文件展示如何用 LLM 做结构化字段抽取，作为主解析通道；
  intent_parser.py 的规则解析可以作为无网络/无 Key 场景下的降级兜底，
  两者互为校验：字段冲突时以 LLM 结果为准，规则结果用于合理性检查
  （例如时间范围是否落在合理区间）。

运行方式：
    export ANTHROPIC_API_KEY=你的key
    python3 llm_intent_parser.py

注意：本文件包含真实可运行的 API 调用逻辑，但当前 Demo 运行环境未配置
API Key，因此本次演示以 intent_parser.py 的规则版本输出作为可复现证据；
比赛提交时请在具备 API Key 的环境下运行本文件，验证 LLM 版本的解析效果。
"""

import os
import json
from datetime import datetime

try:
    import anthropic
except ImportError:
    anthropic = None

SYSTEM_PROMPT = """你是招投标信息聚合系统的意图解析模块。
请从用户的自然语言问题中抽取结构化字段，只输出 JSON，不要输出任何其他文字：

{
  "keyword": "主题/关键词，例如 服务器、充电桩",
  "region": "省份或城市，例如 上海、安徽",
  "time_range": {
    "type": "relative 或 absolute_month",
    "raw": "原文中的时间表达",
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "schedule": {
    "is_recurring": true 或 false,
    "raw": "原文中的频率表达，没有则为 null",
    "cron": "cron 表达式，仅当 is_recurring 为 true 时提供",
    "run_at": "HH:MM 或 immediate，仅当 is_recurring 为 false 时提供"
  }
}

当前日期用于计算相对时间："{today}"
"""


def parse_intent_with_llm(text: str, model: str = "claude-sonnet-5") -> dict:
    if anthropic is None:
        raise RuntimeError("请先安装 anthropic SDK: pip install anthropic --break-system-packages")

    client = anthropic.Anthropic()  # 自动从 ANTHROPIC_API_KEY 环境变量读取
    today = datetime.now().strftime("%Y-%m-%d")

    resp = client.messages.create(
        model=model,
        max_tokens=500,
        system=SYSTEM_PROMPT.format(today=today),
        messages=[{"role": "user", "content": text}],
    )

    raw_text = resp.content[0].text.strip()
    # 兜底去除可能出现的 markdown 代码块标记
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw_text)
    parsed["query"] = text
    return parsed


if __name__ == "__main__":
    demo_queries = [
        "帮我看看下个季度江苏那边有没有什么数据中心的标，每周五早上给我发一次",
        "上个月成都的智慧路灯项目招标情况",
    ]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[提示] 当前环境未检测到 ANTHROPIC_API_KEY，跳过实际调用。")
        print("[说明] 请在配置好 API Key 的环境中运行本文件以验证 LLM 解析效果，")
        print("       本次比赛提交的可复现 Demo 证据以 intent_parser.py 规则版本输出为准。")
    else:
        for q in demo_queries:
            result = parse_intent_with_llm(q)
            print("输入：", q)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("-" * 60)
