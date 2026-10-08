#!/usr/bin/env python3
"""kems-v3 / cockpit MCP HTTP 桥 — 读面最小接线（P0）。

归属（L4 三面标准）：
  实现驻留执行面（Workspace），域内只留数据·声明·证据。
  本脚本把 cockpit.agent_runtime_mcp_server 的 FastMCP 实例以
  streamable HTTP 暴露在本机（默认 http://127.0.0.1:7431/mcp），
  供 WorkBuddy/Doubao 的 ~/.workbuddy/mcp.json 以 type=streamableHttp 注册调用。

背景（2026-10-08 P0 实测）：
  cockpit CLI 的 SSE 路径（mcp.sse_app）在 FastMCP 4.0.5 下已失效
  （AttributeError: 'FastMCP' object has no attribute 'sse_app'）。
  官方注释推荐经 agora-mcp(:7431) 走 BOS 路由，但 agora 当前未运行。
  本桥为最小接线的临时宿主，待 agora 或 cockpit 升级后按 README 收敛，
  不作为长期双轨并行方案。

用法：
  COCKPIT_MCP_PORT=7431 <cockpit .venv>/bin/python mcp-cockpit-http.py

验证：
  python -c "from mcp.client.streamable_http import streamable_http_client; ..."
  目标工具：domains_list / domain_context / kems_status。
"""
from __future__ import annotations

import os
import uvicorn

from cockpit.agent_runtime_mcp_server import mcp


def main() -> None:
    port = int(os.environ.get("COCKPIT_MCP_PORT", "7431"))
    uvicorn.run(mcp.http_app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
