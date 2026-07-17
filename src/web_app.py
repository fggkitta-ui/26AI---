"""
招投标信息智能聚合工具 —— Web UI

提供轻量级的 Web 界面，支持：
- 输入自然语言查询
- 查看意图解析结果
- 触发抓取并下载 Word 报告
- 查看历史任务状态

运行方式：
    python -m src.main --web
    或
    python -m src.web_app
"""

import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify, send_file

from src.intent.rule_parser import parse_intent
from src.scheduler.state_store import get_pushed_fingerprints, make_subscription_id, DB_PATH

OUTPUT_DIR = Path("outputs")

# ---------------------------------------------------------------------------
# HTML 模板
# ---------------------------------------------------------------------------

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>招投标信息智能聚合工具</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                         "Microsoft YaHei", sans-serif;
            background: #f5f5f0;
            color: #2c2c2a;
            line-height: 1.6;
        }
        .container { max-width: 900px; margin: 0 auto; padding: 24px; }
        header {
            text-align: center; padding: 40px 0 24px;
            border-bottom: 2px solid #e0ddd4; margin-bottom: 32px;
        }
        header h1 { font-size: 28px; color: #1a1a18; margin-bottom: 8px; }
        header p { color: #666; font-size: 14px; }
        .card {
            background: #fff; border-radius: 12px; padding: 24px;
            margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }
        .card h2 { font-size: 18px; margin-bottom: 16px; color: #1a1a18; }
        label { display: block; font-weight: 600; margin-bottom: 6px; font-size: 14px; }
        textarea {
            width: 100%; padding: 12px; border: 1px solid #d4d0c8;
            border-radius: 8px; font-size: 15px; resize: vertical;
            min-height: 60px; font-family: inherit;
        }
        textarea:focus { outline: none; border-color: #534AB7; box-shadow: 0 0 0 3px rgba(83,74,183,0.1); }
        .examples { margin-top: 8px; font-size: 13px; color: #888; }
        .examples span {
            display: inline-block; background: #EEEDFE; color: #534AB7;
            padding: 2px 10px; border-radius: 12px; margin: 2px 4px;
            cursor: pointer; transition: background 0.2s;
        }
        .examples span:hover { background: #dcd8f6; }
        .btn {
            display: inline-block; padding: 10px 24px; border: none;
            border-radius: 8px; font-size: 15px; font-weight: 600;
            cursor: pointer; transition: all 0.2s;
            margin-right: 8px; margin-top: 12px;
        }
        .btn-primary { background: #534AB7; color: #fff; }
        .btn-primary:hover { background: #4239a3; }
        .btn-secondary { background: #e0ddd4; color: #2c2c2a; }
        .btn-secondary:hover { background: #d0ccc0; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .result { margin-top: 16px; }
        .result .intent-box {
            background: #f8f7fc; border: 1px solid #e0ddf0;
            border-radius: 8px; padding: 16px; margin-bottom: 16px;
        }
        .result .intent-box h3 { font-size: 14px; color: #534AB7; margin-bottom: 8px; }
        .result .intent-box .fields { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .result .intent-box .field { font-size: 14px; }
        .result .intent-box .field-key { color: #888; }
        .result .intent-box .field-val { color: #2c2c2a; font-weight: 500; }
        .status { padding: 12px; border-radius: 8px; margin-top: 12px; font-size: 14px; }
        .status.success { background: #e1f5ee; color: #04342C; }
        .status.error { background: #fde8e8; color: #8b1a1a; }
        .status.info { background: #e8f0fe; color: #1a3a6b; }
        .file-list { margin-top: 16px; }
        .file-item {
            display: flex; justify-content: space-between; align-items: center;
            padding: 10px 14px; border-bottom: 1px solid #f0efe8;
        }
        .file-item:last-child { border-bottom: none; }
        .file-item .file-name { font-size: 14px; color: #534AB7; }
        .file-item .file-time { font-size: 12px; color: #999; }
        .file-item .file-download { font-size: 13px; color: #534AB7; text-decoration: none; }
        .file-item .file-download:hover { text-decoration: underline; }
        .loading { display: none; text-align: center; padding: 24px; }
        .loading.active { display: block; }
        .spinner {
            display: inline-block; width: 32px; height: 32px;
            border: 3px solid #e0ddd4; border-top-color: #534AB7;
            border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        footer {
            text-align: center; padding: 24px; color: #999; font-size: 13px;
            border-top: 1px solid #e0ddd4; margin-top: 40px;
        }
        .tabs { display: flex; gap: 0; margin-bottom: 24px; }
        .tab {
            padding: 10px 24px; border: 1px solid #d4d0c8;
            background: #f8f7f5; cursor: pointer; font-size: 14px;
            font-weight: 500; transition: all 0.2s;
        }
        .tab:first-child { border-radius: 8px 0 0 8px; }
        .tab:last-child { border-radius: 0 8px 8px 0; }
        .tab.active { background: #534AB7; color: #fff; border-color: #534AB7; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📋 招投标信息智能聚合工具</h1>
            <p>用自然语言描述需求，自动完成"多源抓取 → 清洗去重 → 汇总推送"</p>
        </header>

        <div class="tabs">
            <div class="tab active" onclick="switchTab('query')">🔍 查询招投标信息</div>
            <div class="tab" onclick="switchTab('history')">📂 历史报告</div>
        </div>

        <!-- 查询页 -->
        <div id="tab-query" class="tab-content active">
            <div class="card">
                <h2>输入你的需求</h2>
                <label for="query">用自然语言描述你的招投标信息需求：</label>
                <textarea id="query" placeholder="例如：最近3个月的上海区域内的充电桩招标信息都有哪些，请汇总后每天9:00发送给我"></textarea>
                <div class="examples">
                    快速示例：
                    <span onclick="fillExample('最近1个月的安徽省区域内的服务器招标信息都有哪些')">安徽服务器</span>
                    <span onclick="fillExample('最近3个月的上海区域内的充电桩招标信息都有哪些')">上海充电桩</span>
                    <span onclick="fillExample('2026年4月北京充电桩相关的招标信息都有哪些')">北京充电桩</span>
                    <span onclick="fillExample('最近2周河南省的光伏电站招标信息都有哪些')">河南光伏</span>
                </div>
                <div style="margin-top: 8px;">
                    <label style="display: inline; font-weight: normal; font-size: 13px;">
                        <input type="checkbox" id="demo-mode"> 演示模式（使用内置数据，无需网络）
                    </label>
                </div>
                <button class="btn btn-primary" onclick="submitQuery()">🔍 开始聚合</button>
                <button class="btn btn-secondary" onclick="parseOnly()">📋 仅解析意图</button>
            </div>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p style="margin-top: 12px; color: #888;">正在抓取并处理中，请稍候...</p>
            </div>

            <div class="result" id="result"></div>
        </div>

        <!-- 历史报告页 -->
        <div id="tab-history" class="tab-content">
            <div class="card">
                <h2>生成的报告文件</h2>
                <div class="file-list" id="file-list">
                    <p style="color: #999;">加载中...</p>
                </div>
            </div>
            <div class="card">
                <h2>定时任务状态</h2>
                <div id="job-status">
                    <p style="color: #999;">加载中...</p>
                </div>
            </div>
        </div>

        <footer>
            招投标信息智能聚合工具 · 超聚变 AI 先锋大赛参赛作品
        </footer>
    </div>

    <script>
        function switchTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelector(`.tab:nth-child(${name === 'query' ? '1' : '2'})`).classList.add('active');
            document.getElementById('tab-' + name).classList.add('active');
            if (name === 'history') loadHistory();
        }

        function fillExample(text) {
            document.getElementById('query').value = text;
        }

        function parseOnly() {
            const query = document.getElementById('query').value.trim();
            if (!query) { alert('请输入查询内容'); return; }
            fetch('/api/parse', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query: query})
            })
            .then(r => r.json())
            .then(data => {
                const div = document.getElementById('result');
                div.innerHTML = renderIntent(data);
            });
        }

        function submitQuery() {
            const query = document.getElementById('query').value.trim();
            if (!query) { alert('请输入查询内容'); return; }
            const demo = document.getElementById('demo-mode').checked;

            document.getElementById('loading').classList.add('active');
            document.getElementById('result').innerHTML = '';

            fetch('/api/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query: query, demo: demo})
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('loading').classList.remove('active');
                const div = document.getElementById('result');
                if (data.error) {
                    div.innerHTML = `<div class="status error">❌ ${data.error}</div>`;
                } else {
                    div.innerHTML = renderIntent(data.intent) + `
                        <div class="status success">
                            ✅ 执行成功！共找到 ${data.item_count} 条招投标信息
                            ${data.is_incremental ? '(增量推送)' : ''}
                        </div>
                        <p style="margin-top:12px;">
                            📄 <a href="/api/download/${data.filename}" style="color:#534AB7;">
                                下载 Word 报告: ${data.filename}
                            </a>
                        </p>
                    `;
                }
            })
            .catch(err => {
                document.getElementById('loading').classList.remove('active');
                document.getElementById('result').innerHTML =
                    `<div class="status error">❌ 请求失败: ${err.message}</div>`;
            });
        }

        function renderIntent(intent) {
            const tr = intent.time_range || {};
            const sc = intent.schedule || {};
            return `
                <div class="intent-box">
                    <h3>📋 意图解析结果</h3>
                    <div class="fields">
                        <div class="field"><span class="field-key">关键词：</span><span class="field-val">${intent.keyword || '未识别'}</span></div>
                        <div class="field"><span class="field-key">区域：</span><span class="field-val">${intent.region || '未指定'}</span></div>
                        <div class="field"><span class="field-key">时间范围：</span><span class="field-val">${tr.raw || '未识别'} (${tr.start || '?'} ~ ${tr.end || '?'})</span></div>
                        <div class="field"><span class="field-key">调度方式：</span><span class="field-val">${sc.is_recurring ? '周期定时 (cron: ' + sc.cron + ')' : (sc.run_at || '立即执行')}</span></div>
                    </div>
                </div>
            `;
        }

        function loadHistory() {
            fetch('/api/files')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('file-list');
                    if (!data.files || data.files.length === 0) {
                        list.innerHTML = '<p style="color:#999;">暂无生成的报告文件。</p>';
                        return;
                    }
                    list.innerHTML = data.files.map(f => `
                        <div class="file-item">
                            <span class="file-name">📄 ${f.name}</span>
                            <span class="file-time">${f.time}</span>
                            <a class="file-download" href="/api/download/${f.name}">下载</a>
                        </div>
                    `).join('');
                });

            fetch('/api/jobs')
                .then(r => r.json())
                .then(data => {
                    const div = document.getElementById('job-status');
                    if (!data.count) {
                        div.innerHTML = '<p style="color:#999;">暂无定时任务和已推送记录。</p>';
                        return;
                    }
                    div.innerHTML = `<p>共 ${data.count} 条已推送记录（增量去重依据）</p>`;
                });
        }

        // 初始加载
        loadHistory();
    </script>
</body>
</html>"""


def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(INDEX_TEMPLATE)

    @app.route("/api/parse", methods=["POST"])
    def api_parse():
        """仅解析意图，不执行抓取。"""
        data = request.get_json()
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "查询不能为空"}), 400
        intent = parse_intent(query)
        return jsonify(intent)

    @app.route("/api/run", methods=["POST"])
    def api_run():
        """执行完整的抓取汇总流程。"""
        from src.main import run_pipeline

        data = request.get_json()
        query = data.get("query", "").strip()
        demo = data.get("demo", False)

        if not query:
            return jsonify({"error": "查询不能为空"}), 400

        try:
            intent = parse_intent(query)
            output_path = run_pipeline(query, demo_mode=demo)
            filename = Path(output_path).name

            # 统计结果条目数
            item_count = 0
            try:
                from docx import Document
                doc = Document(output_path)
                # 统计 heading level 2 的数量（每条信息一个标题）
                item_count = sum(1 for p in doc.paragraphs if p.style.name.startswith("Heading 2"))
            except Exception:
                pass

            return jsonify({
                "intent": intent,
                "filename": filename,
                "item_count": item_count,
                "is_incremental": False,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/files")
    def api_files():
        """列出已生成的报告文件。"""
        files = []
        if OUTPUT_DIR.exists():
            for f in sorted(OUTPUT_DIR.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "size": stat.st_size,
                })
        return jsonify({"files": files[:20]})

    @app.route("/api/download/<filename>")
    def api_download(filename: str):
        """下载指定的报告文件。"""
        filepath = OUTPUT_DIR / filename
        if not filepath.exists():
            return jsonify({"error": "文件不存在"}), 404
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    @app.route("/api/jobs")
    def api_jobs():
        """获取定时任务状态。"""
        import sqlite3
        if not DB_PATH.exists():
            return jsonify({"count": 0, "records": []})
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT subscription_id, COUNT(*) as cnt FROM pushed_items GROUP BY subscription_id"
        ).fetchall()
        conn.close()
        return jsonify({
            "count": len(rows),
            "subscriptions": [{"id": r[0], "pushed_count": r[1]} for r in rows],
        })

    return app


if __name__ == "__main__":
    app = create_app()
    print("启动 Web UI: http://127.0.0.1:8080")
    app.run(host="127.0.0.1", port=8080, debug=True)
