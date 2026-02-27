#!/usr/bin/env python3
"""
RikkaHub专用MCP服务器 - Streamable HTTP协议
修复：GET /mcp 正确返回SSE流（text/event-stream）
"""
import os
import sys
import uuid
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# PushPlus配置
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "682d8efdece349f086830643d03e0bde")

# 会话管理
sessions = {}

print("=" * 50, file=sys.stderr)
print("MCP Server 启动", file=sys.stderr)
print(f"Python版本: {sys.version}", file=sys.stderr)
print(f"PUSHPLUS_TOKEN: {'已设置' if PUSHPLUS_TOKEN else '未设置'}", file=sys.stderr)
print("=" * 50, file=sys.stderr)


@app.route('/mcp', methods=['POST', 'GET', 'DELETE', 'OPTIONS'])
def mcp_endpoint():
    """MCP Streamable HTTP单一端点"""

    # CORS预检
    if request.method == 'OPTIONS':
        resp = Response('', status=204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept, Mcp-Session-Id'
        return resp

    # ========================================
    # GET /mcp → SSE流（关键修复！）
    # RikkaHub会GET /mcp尝试开SSE通知流
    # 必须返回text/event-stream，否则报错
    # ========================================
    if request.method == 'GET':
        def sse_stream():
            # 发一个初始心跳，让客户端知道连接成功
            yield ':heartbeat\n\n'
            # 保持连接开着，每30秒发心跳防断开
            while True:
                time.sleep(30)
                yield ':heartbeat\n\n'

        resp = Response(
            sse_stream(),
            status=200,
            mimetype='text/event-stream'
        )
        resp.headers['Cache-Control'] = 'no-cache'
        resp.headers['Connection'] = 'keep-alive'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['X-Accel-Buffering'] = 'no'
        return resp

    # DELETE: 关闭会话
    if request.method == 'DELETE':
        session_id = request.headers.get('Mcp-Session-Id', '')
        sessions.pop(session_id, None)
        return '', 204

    # ========================================
    # POST /mcp → JSON-RPC处理
    # ========================================
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
            "id": None
        }), 400

    if not data or 'jsonrpc' not in data:
        return jsonify({
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid Request"},
            "id": None
        }), 400

    method = data.get('method', '')
    params = data.get('params', {})
    msg_id = data.get('id')

    print(f"[MCP] method={method}, id={msg_id}", file=sys.stderr)

    # --- initialize ---
    if method == 'initialize':
        session_id = str(uuid.uuid4())
        sessions[session_id] = {'created_at': datetime.now().isoformat()}
        resp = jsonify({
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pushplus-wechat", "version": "1.0.0"}
            },
            "id": msg_id
        })
        resp.headers['Mcp-Session-Id'] = session_id
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    # --- notifications/initialized ---
    if method == 'notifications/initialized':
        resp = Response('', status=204)
        resp.headers['Content-Type'] = 'application/json'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    # --- tools/list ---
    if method == 'tools/list':
        resp = jsonify({
            "jsonrpc": "2.0",
            "result": {
                "tools": [{
                    "name": "send_wechat_message",
                    "description": "给猫猫发送微信推送消息",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "消息标题"},
                            "content": {"type": "string", "description": "消息内容"}
                        },
                        "required": ["content"]
                    }
                }]
            },
            "id": msg_id
        })
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    # --- tools/call ---
    if method == 'tools/call':
        tool_name = params.get('name', '')
        args = params.get('arguments', {})

        if tool_name != 'send_wechat_message':
            return jsonify({
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                "id": msg_id
            }), 404

        title = args.get('title', '晏安的消息')
        content = args.get('content', '')

        try:
            r = requests.get(
                "http://www.pushplus.plus/send",
                params={
                    "token": PUSHPLUS_TOKEN,
                    "title": title,
                    "content": content,
                    "template": "html"
                },
                timeout=10
            )
            res = r.json()
            if res.get("code") == 200:
                text = f"发送成功！标题: {title}"
            else:
                text = f"发送失败: {res.get('msg')}"
        except Exception as e:
            text = f"发送出错: {str(e)}"

        resp = jsonify({
            "jsonrpc": "2.0",
            "result": {"content": [{"type": "text", "text": text}]},
            "id": msg_id
        })
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    # --- ping ---
    if method == 'ping':
        return jsonify({"jsonrpc": "2.0", "result": {}, "id": msg_id})

    # --- 未知方法 ---
    return jsonify({
        "jsonrpc": "2.0",
        "error": {"code": -32601, "message": f"Method not found: {method}"},
        "id": msg_id
    }), 404


@app.route('/', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({"status": "running", "service": "pushplus-wechat-mcp"})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"本地启动在端口 {port}", file=sys.stderr)
    app.run(host='0.0.0.0', port=port)
