"""eCOS v6 Runtime MCP Server.

暴露 Runtime 状态、矩阵调度、协议注册表与 MOF 动态约束拦截。
兼容 FastMCP (推荐, 需要 fastmcp 库) 与纯 Python 测试模式。

用法:
    python -m runtime.mcp_server           # FastMCP stdio 模式
    python -m runtime.mcp_server --test    # 测试模式 (直接调用并打印 JSON)
    python -m runtime.mcp_server --list    # 列出所有工具
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def _get_runtime_state() -> dict:
    """读取 runtime 运行状态 (从 state_schema / 本地文件)."""
    return {
        "status": "HEALTHY",
        "version": "6.0.0",
        "node_id": "ecos-runtime-01",
        "mode": "standalone",
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


def handle_health() -> dict:
    """runtime_health: 获取 runtime 节点健康状态."""
    state = _get_runtime_state()
    return {
        "status": state["status"],
        "node_id": state["node_id"],
        "version": state["version"],
        "mode": state["mode"],
        "uptime_seconds": 0,
        "active_tasks": 0,
        "timestamp": state["timestamp"],
    }


def handle_matrix_list() -> dict:
    """runtime_matrix_list: 列出所有矩阵单元及其配置."""
    try:
        from runtime.adapters.matrix_adapter import MatrixAdapter

        adapter = MatrixAdapter()
        cells = adapter.list_cells()
        return {
            "cells": cells,
            "total": len(cells),
            "source": "MatrixAdapter",
        }
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {
            "cells": [
                {
                    "cell_id": "cell-dev-01",
                    "type": "execution",
                    "status": "ready",
                    "capacity": 4,
                },
                {
                    "cell_id": "cell-eval-01",
                    "type": "evaluation",
                    "status": "ready",
                    "capacity": 2,
                },
                {
                    "cell_id": "cell-mon-01",
                    "type": "monitoring",
                    "status": "active",
                    "capacity": 1,
                },
            ],
            "total": 3,
            "source": "fallback",
            "warning": f"Adapter not available: {e}",
        }


def handle_protocol_list() -> dict:
    """runtime_protocol_list: 列出所有已注册的协议及其状态."""
    try:
        from runtime.protocol import ProtocolRegistry

        registry = ProtocolRegistry()
        protocols = registry.list_protocols()
        return {
            "protocols": protocols,
            "total": len(protocols),
            "source": "ProtocolRegistry",
        }
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {
            "protocols": [
                {
                    "protocol_id": "proto-a2a-v1",
                    "name": "Agent-to-Agent Communication Protocol",
                    "version": "1.0.0",
                    "status": "active",
                    "layer": "L1",
                },
                {
                    "protocol_id": "proto-bos-v2",
                    "name": "BOS Service Resolution Protocol",
                    "version": "2.0.0",
                    "status": "active",
                    "layer": "I0",
                },
                {
                    "protocol_id": "proto-mcp-v1",
                    "name": "Model Context Protocol Bridge",
                    "version": "1.0.0",
                    "status": "active",
                    "layer": "L1",
                },
                {
                    "protocol_id": "proto-kems-v1",
                    "name": "Knowledge & Entity Management Schema",
                    "version": "1.0.0",
                    "status": "active",
                    "layer": "L4",
                },
            ],
            "total": 4,
            "source": "fallback",
            "warning": f"Registry not available: {e}",
        }


def handle_protocol_get(protocol_id: str) -> dict:
    """runtime_protocol_get: 获取指定协议的详细定义."""
    all_protos = handle_protocol_list()["protocols"]
    for p in all_protos:
        if p.get("protocol_id") == protocol_id:
            return {
                "protocol": p,
                "schema": {
                    "type": "object",
                    "protocol_id": protocol_id,
                    "fields": ["header", "payload", "signature", "metadata"],
                },
            }
    return {"error": f"Protocol not found: {protocol_id}"}


def handle_ontology() -> dict:
    """runtime_ontology_get: 获取当前运行时的本体映射和类型定义."""
    return {
        "entities": [
            {
                "type": "Task",
                "layer": "L1",
                "description": "Atomic unit of execution",
            },
            {
                "type": "Agent",
                "layer": "L3",
                "description": "Autonomous execution entity",
            },
            {
                "type": "Domain",
                "layer": "L4",
                "description": "Bounded business context",
            },
            {
                "type": "MatrixCell",
                "layer": "L1",
                "description": "Execution container unit",
            },
            {
                "type": "Protocol",
                "layer": "L0",
                "description": "Contract interface specification",
            },
        ],
        "relations": [
            {
                "from": "Agent",
                "to": "Task",
                "relation": "executes",
                "cardinality": "1:N",
            },
            {
                "from": "Task",
                "to": "MatrixCell",
                "relation": "runs_in",
                "cardinality": "N:1",
            },
            {
                "from": "Agent",
                "to": "Domain",
                "relation": "belongs_to",
                "cardinality": "N:1",
            },
            {
                "from": "Task",
                "to": "Protocol",
                "relation": "conforms_to",
                "cardinality": "N:1",
            },
        ],
        "layers": ["L0 (SSOT)", "L1 (Runtime)", "L2 (Knowledge)", "L3 (Agent)", "L4 (Domain)"],
        "version": "1.0.0",
    }


def handle_brief() -> dict:
    """runtime_brief: 获取运行时整体状态摘要 (聚合健康度、单元数、协议数)."""
    health = handle_health()
    matrix = handle_matrix_list()
    protocols = handle_protocol_list()
    return {
        "status": health["status"],
        "node_id": health["node_id"],
        "version": health["version"],
        "summary": {
            "matrix_cells_total": matrix["total"],
            "protocols_active": protocols["total"],
            "mode": health["mode"],
        },
        "timestamp": health["timestamp"],
    }


def handle_kv_get(key: str) -> dict:
    """runtime_kv_get: 读取运行时状态 KV (支持 system_state, matrix_config, domain_map 等)."""
    kv_store = {
        "system_state": {
            "epoch": 1,
            "phase": "v6-production",
            "maintenance_mode": False,
        },
        "matrix_config": {
            "default_timeout_ms": 30000,
            "max_concurrent_cells": 16,
            "retry_limit": 3,
        },
        "domain_map": {
            "domains": ["work-weijian", "work-guozhuan", "family", "personal", "vault"],
            "default_domain": "work-weijian",
        },
        "governance": {
            "audit_enabled": True,
            "ssb_logging": True,
            "strict_mode": True,
        },
    }
    if key in kv_store:
        return {"key": key, "value": kv_store[key], "found": True}
    return {"key": key, "value": None, "found": False, "error": f"Key not found: {key}"}


# ── agent-runtime 迁移处理函数 (调用 executor 内部实现) ───────────────────


def handle_agent_list_tools() -> dict:
    """列出当前注册的所有 Agent 工具 (tools.py)."""
    from runtime.executor.tools import get_tool_registry

    try:
        registry = get_tool_registry()
        return {"tools": registry.list_tools(), "count": len(registry.list_tools())}
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {"tools": [], "count": 0, "error": f"{type(e).__name__}: {e}"}


def handle_agent_list() -> dict:
    """列出可用 Agent (AgentManager)."""
    from runtime.executor.agent_manager import AgentManager

    try:
        mgr = AgentManager()
        agents = mgr.list_agents()
        return {"agents": agents, "count": len(agents)}
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {"agents": [], "count": 0, "error": f"{type(e).__name__}: {e}"}


def handle_agent_status() -> dict:
    """查询 Agent Runtime 综合状态 (AgentRuntime / AgentManager)."""
    from runtime.executor.agent_manager import AgentManager
    from runtime.executor.engine import AgentRuntime

    try:
        rt = AgentRuntime()
        mgr = AgentManager()
        return {
            "status": "ready",
            "model": rt.model,
            "agent_count": len(mgr.list_agents()),
            "agents": mgr.list_agents(),
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {"error": f"{type(e).__name__}: {e}"}


def handle_agent_task_status(task_id: str) -> dict:
    """查询任务状态 (TaskScheduler.get_status)."""
    from runtime.executor.task_scheduler import TaskScheduler

    try:
        sched = TaskScheduler()
        status = sched.get_status(task_id)
        return {"task_id": task_id, "status": str(status)}
    except KeyError:
        return {"error": f"Task not found: {task_id}"}
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {"error": f"{type(e).__name__}: {e}"}


def handle_agent_run_task(prompt: str, tools: str = "") -> dict:
    """执行任务 (AgentRuntime.run_task). 注意: 需要 LLM provider 才能真跑."""
    from runtime.executor.engine import AgentRuntime

    try:
        rt = AgentRuntime()
        tools_enabled = [t.strip() for t in tools.split(",") if t.strip()] or None
        return rt.run_task(prompt, tools_enabled=tools_enabled)
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {"error": f"{type(e).__name__}: {e}"}


def handle_agent_chat(message: str, history: str = "[]") -> dict:
    """对话交互 (AgentRuntime chat). 需要 LLM provider."""
    import json as _json

    from runtime.executor.engine import AgentRuntime

    try:
        rt = AgentRuntime()
        messages = [{"role": "system", "content": "You are a helpful assistant."}]
        messages.extend(_json.loads(history) if history and history != "[]" else [])
        messages.append({"role": "user", "content": message})
        result = rt._call_llm(messages)
        return {"response": result.get("content", ""), "model": rt.model}
    except Exception as e:  # noqa: BLE001  # defensive fallback
        return {"error": f"{type(e).__name__}: {e}"}


def handle_agent_execute(prompt: str) -> dict:
    """执行任务 (execute = run_task 语义, 别名)."""
    return handle_agent_run_task(prompt)


def handle_governance_preflight(
    tool_name: str,
    arguments: dict,
    caller_layer: str = "L3",
    caller_domain: str = "default",
) -> dict:
    """runtime_governance_preflight: MOF 运行时动作 Pre-flight 语义拦截与架构合规性检查."""
    from runtime.governance.interceptor import GovernanceInterceptor

    interceptor = GovernanceInterceptor()
    allowed, diag = interceptor.intercept_tool_call(
        tool_name=tool_name,
        arguments=arguments,
        caller_layer=caller_layer,
        caller_domain=caller_domain,
    )
    if not allowed and diag:
        return diag
    return {
        "status": "ALLOWED",
        "tool_name": tool_name,
        "caller_layer": caller_layer,
        "caller_domain": caller_domain,
        "note": "MOF L0 architecture constraints verified",
    }


def handle_governance_guardrails(
    domain: str = "default",
    layer: str = "L3",
    max_rules: int = 5,
) -> dict:
    """runtime_governance_guardrails: 生成注入 Agent System Prompt 的轻量架构约束块."""
    from runtime.governance.interceptor import GovernanceInterceptor

    interceptor = GovernanceInterceptor()
    prompt = interceptor.get_guardrail_prompt(domain=domain, layer=layer, max_rules=max_rules)
    return {
        "domain": domain,
        "layer": layer,
        "guardrail_prompt": prompt,
    }


def handle_governance_explain(rule_id: str) -> dict:
    """runtime_governance_explain: 查询指定 MOF 架构规则的详细动机与代码自愈范式."""
    from runtime.governance.interceptor import GovernanceInterceptor

    interceptor = GovernanceInterceptor()
    return interceptor.explain_rule(rule_id)


def handle_documents_guardrails(domain: str = "work-weijian") -> dict:
    """runtime_documents_guardrails: 生成 Documents 双平面提示词约束块 (ADR-0191)."""
    from runtime.governance.interceptor import GovernanceInterceptor

    interceptor = GovernanceInterceptor()
    prompt = interceptor.get_documents_guardrail_prompt(domain_id=domain)
    return {
        "domain": domain,
        "documents_guardrail_prompt": prompt,
    }


def handle_documents_audit(path: str = "~/Documents", domain: str = "default") -> dict:
    """runtime_documents_audit: 扫描 Documents 内容域是否包含代码或环境违规 (ADR-0191)."""
    try:
        from ecos.ssot.compiler.path_inspector import PathBoundaryInspector

        inspector = PathBoundaryInspector()
        target = Path(path).expanduser().resolve()
        violations = []
        scanned = 0
        if target.exists():
            for p in target.rglob("*"):
                if p.is_file():
                    scanned += 1
                    res = inspector.inspect_write(str(p), caller_domain=domain)
                    if not res.passed:
                        for v in res.violations:
                            violations.append({"path": str(p), **v.to_dict()})
        return {
            "target": str(target),
            "files_scanned": scanned,
            "violations_count": len(violations),
            "violations": violations,
            "status": "PASS" if not violations else "VIOLATIONS_FOUND",
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
def _ensure_ecos_path() -> None:
    import sys

    ecos_src = Path(__file__).resolve().parent.parent.parent.parent / "ecos" / "src"
    if ecos_src.exists() and str(ecos_src) not in sys.path:
        sys.path.insert(0, str(ecos_src))


def handle_domain_compliance_audit(target_text_or_path: str, domain: str = "auto") -> dict:
    """runtime_domain_compliance_audit: 审查业务规划、需求方案或文本的领域政策红线合规性 (ADR-0193)."""
    try:
        _ensure_ecos_path()
        from ecos.ssot.compiler.policy_inspector import PolicyComplianceInspector

        inspector = PolicyComplianceInspector()
        p = Path(target_text_or_path).expanduser().resolve()
        if p.exists() and p.is_file():
            report = inspector.audit_file(p, domain=domain)
        else:
            report = inspector.audit_text(target_text_or_path, domain=domain)
        return report.to_dict()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def handle_pitfall_check(path: str = ".") -> dict:
    """runtime_pitfall_check: 静态扫描代码与配置文件中的已知架构反模式与踩坑特征 (ADR-0194)."""
    try:
        _ensure_ecos_path()
        from ecos.ssot.compiler.pitfall_inspector import PitfallInspector

        inspector = PitfallInspector()
        target = Path(path).expanduser().resolve()
        matches = []
        if target.is_file():
            res = inspector.scan_file(target)
            matches.extend(res.matches)
        elif target.is_dir():
            for f in target.rglob("*.py"):
                res = inspector.scan_file(f)
                matches.extend(res.matches)
        return {
            "target": str(target),
            "total_matches": len(matches),
            "passed": len(matches) == 0,
            "matches": [
                {
                    "pitfall_id": m.pitfall_id,
                    "title": m.title,
                    "severity": m.severity,
                    "line": m.line_number,
                    "snippet": m.matched_snippet,
                    "lesson": m.lesson,
                    "recipe": m.recipe,
                }
                for m in matches
            ],
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ── FastMCP server ──────────────────────────────────────────────────────────

try:
    from fastmcp import FastMCP

    mcp = FastMCP("ecos-runtime")

    @mcp.tool()
    def runtime_health() -> dict:
        return handle_health()

    @mcp.tool()
    def runtime_matrix_list() -> dict:
        return handle_matrix_list()

    @mcp.tool()
    def runtime_protocol_list() -> dict:
        return handle_protocol_list()

    @mcp.tool()
    def runtime_protocol_get(protocol_id: str) -> dict:
        return handle_protocol_get(protocol_id)

    @mcp.tool()
    def runtime_ontology_get() -> dict:
        return handle_ontology()

    @mcp.tool()
    def runtime_brief() -> dict:
        return handle_brief()

    @mcp.tool()
    def runtime_kv_get(key: str) -> dict:
        return handle_kv_get(key)

    @mcp.tool()
    def runtime_governance_preflight(
        tool_name: str,
        arguments: dict,
        caller_layer: str = "L3",
        caller_domain: str = "default",
    ) -> dict:
        return handle_governance_preflight(tool_name, arguments, caller_layer, caller_domain)

    @mcp.tool()
    def runtime_governance_guardrails(
        domain: str = "default",
        layer: str = "L3",
        max_rules: int = 5,
    ) -> dict:
        return handle_governance_guardrails(domain, layer, max_rules)

    @mcp.tool()
    def runtime_governance_explain(rule_id: str) -> dict:
        return handle_governance_explain(rule_id)

    @mcp.tool()
    def runtime_documents_guardrails(domain: str = "work-weijian") -> dict:
        return handle_documents_guardrails(domain)

    @mcp.tool()
    def runtime_documents_audit(path: str = "~/Documents", domain: str = "default") -> dict:
        return handle_documents_audit(path, domain)

    @mcp.tool()
    def runtime_domain_compliance_audit(target_text_or_path: str, domain: str = "auto") -> dict:
        return handle_domain_compliance_audit(target_text_or_path, domain)

    @mcp.tool()
    def runtime_pitfall_check(path: str = ".") -> dict:
        return handle_pitfall_check(path)

    # agent-runtime 整合工具 (调 executor 核心 API, 消除 cockpit 壳层)
    @mcp.tool()
    def runtime_agent_list_tools() -> dict:
        return handle_agent_list_tools()

    @mcp.tool()
    def runtime_agent_list() -> dict:
        return handle_agent_list()

    @mcp.tool()
    def runtime_agent_status() -> dict:
        return handle_agent_status()

    @mcp.tool()
    def runtime_agent_task_status(task_id: str) -> dict:
        return handle_agent_task_status(task_id)

    @mcp.tool()
    def runtime_agent_run_task(prompt: str, tools: str = "") -> dict:
        return handle_agent_run_task(prompt, tools)

    @mcp.tool()
    def runtime_agent_chat(message: str, history: str = "[]") -> dict:
        return handle_agent_chat(message, history)

    @mcp.tool()
    def runtime_agent_execute(prompt: str) -> dict:
        return handle_agent_execute(prompt)

except ImportError as _e:
    mcp = None
    _import_error = _e


def main():
    parser = argparse.ArgumentParser(description="eCOS v6 Runtime MCP Server")
    parser.add_argument("--test", type=str, help="测试模式: 工具名")
    parser.add_argument("--list", action="store_true", help="列出所有工具")
    args = parser.parse_args()

    # Enable KEI Sandbox
    try:
        from runtime.kei_sandbox import enable_sandbox

        kei_config = str(Path(__file__).resolve().parent.parent.parent / "kei.yaml")
        enable_sandbox(config_path=kei_config)
    except ImportError:
        pass  # defensive fallback

    # 测试模式: 直接调用并打印
    if args.test:
        handlers = {
            "health": handle_health,
            "matrix": handle_matrix_list,
            "protocols": handle_protocol_list,
            "ontology": handle_ontology,
            "brief": handle_brief,
            "documents_guardrails": handle_documents_guardrails,
            "domain_compliance": lambda: handle_domain_compliance_audit("医疗平台预算1000万无专家论证", "work-weijian"),
            "pitfall_check": handle_pitfall_check,
        }
        handler = handlers.get(args.test)
        if handler:
            print(json.dumps(handler(), ensure_ascii=False, indent=2))
        else:
            print(f"未知测试: {args.test}")
        return

    if args.list:
        tools = [
            "runtime_health",
            "runtime_matrix_list",
            "runtime_protocol_list",
            "runtime_protocol_get",
            "runtime_ontology_get",
            "runtime_brief",
            "runtime_kv_get",
            "runtime_governance_preflight",
            "runtime_governance_guardrails",
            "runtime_governance_explain",
            "runtime_documents_guardrails",
            "runtime_documents_audit",
            "runtime_domain_compliance_audit",
            "runtime_pitfall_check",
            "runtime_agent_list_tools",
            "runtime_agent_list",
            "runtime_agent_status",
            "runtime_agent_task_status",
            "runtime_agent_run_task",
            "runtime_agent_chat",
            "runtime_agent_execute",
        ]
        for t in tools:
            print(f"  {t}")
        return

    # MCP stdio 模式
    if mcp is None:
        print(f"⚠️  fastmcp 库未安装: {_import_error}")
        print("   测试模式可用: --test health|matrix|protocols|ontology|brief")
        print("   列出工具: --list")
        return

    mcp.run()


if __name__ == "__main__":
    main()
