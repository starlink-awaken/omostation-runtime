"""Runtime MOF Governance Pre-flight Interceptor.

Intercepts Agent tool calls before physical execution to enforce MOF L0 architecture
constraints, boundary permissions, and shell safety rules in real time.
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PreFlightViolationError(Exception):
    """Raised when an Agent action violates MOF governance constraints."""

    def __init__(
        self, rule_id: str, violation_code: str, summary: str, remediation: str
    ) -> None:
        super().__init__(f"[{rule_id} / {violation_code}] {summary}: {remediation}")
        self.rule_id = rule_id
        self.violation_code = violation_code
        self.summary = summary
        self.remediation = remediation


@dataclass
class ToolCallAuditRecord:
    timestamp: float
    tool_name: str
    allowed: bool
    caller_layer: str
    caller_domain: str
    violation_code: str | None = None
    duration_ms: float = 0.0


class GovernanceInterceptor:
    """Real-time Pre-flight Interceptor for Agent actions."""

    def __init__(self) -> None:
        self._init_inspectors()
        self.audit_log: list[ToolCallAuditRecord] = []

    def _init_inspectors(self) -> None:
        try:
            from ecos.ssot.compiler.ast_inspector import AstDependencyInspector
            from ecos.ssot.compiler.command_inspector import CommandSafetyInspector
            from ecos.ssot.compiler.path_inspector import PathBoundaryInspector

            self.ast_inspector = AstDependencyInspector()
            self.path_inspector = PathBoundaryInspector()
            self.command_inspector = CommandSafetyInspector()
        except ImportError:
            # Standalone fallback if ecos is not directly in pythonpath
            self.ast_inspector = _FallbackAstInspector()
            self.path_inspector = _FallbackPathInspector()
            self.command_inspector = _FallbackCommandInspector()

    def intercept_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        caller_layer: str = "L3",
        caller_domain: str = "default",
    ) -> tuple[bool, dict[str, Any] | None]:
        start = time.perf_counter()
        allowed = True
        diag: dict[str, Any] | None = None

        # 1. File write / modification inspection
        if tool_name in (
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
        ):
            target_file = str(
                arguments.get("TargetFile") or arguments.get("target_file") or ""
            )
            code_content = str(
                arguments.get("CodeContent")
                or arguments.get("ReplacementContent")
                or arguments.get("replacement_content")
                or ""
            )

            # 1a. Check path boundary
            path_res = self.path_inspector.inspect_write(
                target_file, caller_domain=caller_domain
            )
            if not path_res.passed:
                v = path_res.violations[0]
                allowed = False
                diag = self._build_diagnostic(v)

            # 1b. Check AST for Python code
            elif target_file.endswith(".py") or "import " in code_content:
                violations = self.ast_inspector.inspect_code(
                    code_content, caller_layer=caller_layer
                )
                if violations:
                    v = violations[0]
                    allowed = False
                    diag = self._build_diagnostic(v)

            # 1c. Anti-Escape check for Shell scripts written to disk
            elif target_file.endswith((".sh", ".bash", ".zsh")):
                cmd_res = self.command_inspector.inspect_command(code_content)
                if not cmd_res.passed:
                    v = cmd_res.violations[0]
                    allowed = False
                    diag = self._build_diagnostic(v)

        # 2. Shell command execution inspection
        elif tool_name in ("run_command", "execute_command"):
            command_line = str(
                arguments.get("CommandLine") or arguments.get("command_line") or ""
            )
            cmd_res = self.command_inspector.inspect_command(command_line)
            if not cmd_res.passed:
                v = cmd_res.violations[0]
                allowed = False
                diag = self._build_diagnostic(v)

        # 3. MCP cross-layer invocation
        elif tool_name == "call_mcp_tool":
            server_name = str(arguments.get("ServerName") or "")
            if caller_layer == "L3" and server_name == "l4_kernel_private":
                allowed = False
                diag = {
                    "status": "REJECTED",
                    "error_type": "MOF_CONSTRAINT_VIOLATION",
                    "violation": {
                        "rule_id": "X1-C02",
                        "violation_code": "E-L0-002",
                        "severity": "required",
                        "summary": "禁止绕过 Agora 直连底层私有 MCP 服务",
                        "detail": f"在 {caller_layer} 层直接请求调用 '{server_name}'",
                        "remediation": "根据 L0 架构规范，所有跨层能力必须经由 Agora Gateway 路由",
                        "offending_symbol": server_name,
                    },
                }

        duration_ms = (time.perf_counter() - start) * 1000
        self.audit_log.append(
            ToolCallAuditRecord(
                timestamp=time.time(),
                tool_name=tool_name,
                allowed=allowed,
                caller_layer=caller_layer,
                caller_domain=caller_domain,
                violation_code=diag["violation"]["violation_code"] if diag else None,
                duration_ms=duration_ms,
            )
        )

        return allowed, diag

    def enforce(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        caller_layer: str = "L3",
        caller_domain: str = "default",
    ) -> None:
        allowed, diag = self.intercept_tool_call(
            tool_name, arguments, caller_layer=caller_layer, caller_domain=caller_domain
        )
        if not allowed and diag:
            v = diag["violation"]
            raise PreFlightViolationError(
                rule_id=v["rule_id"],
                violation_code=v["violation_code"],
                summary=v["summary"],
                remediation=v["remediation"],
            )

    def get_guardrail_prompt(
        self, domain: str = "default", layer: str = "L3", max_rules: int = 5
    ) -> str:
        """Synthesize active MOF guardrail block for Agent System Prompts."""
        try:
            from ecos.ssot.compiler.context_synthesizer import MOFContextSynthesizer

            return MOFContextSynthesizer().synthesize_guardrails(
                domain=domain, layer=layer, max_rules=max_rules
            )
        except ImportError:
            return (
                f'<mof_architecture_guardrails domain="{domain}" layer="{layer}">\n'
                "- [E-L0-002: REQUIRED] 禁止跨层直接 import 私有模块，跨域必须通过 agora.client 统一路由。\n"
                "- [E-CMD-001: REQUIRED] 禁止使用 pip install -g/--user 等全局污染命令，依赖必须使用 uv 管理。\n"
                "- [E-PATH-001: REQUIRED] 文件写操作必须局限于当前 Domain 目录与指定公开产物路径。\n"
                "</mof_architecture_guardrails>"
            )

    def explain_rule(self, rule_id: str) -> dict[str, Any]:
        """Provide detailed rule explanation, motivation, and code recipe."""
        try:
            from ecos.ssot.compiler.context_synthesizer import MOFContextSynthesizer

            res = MOFContextSynthesizer().explain_rule(rule_id)
            if res:
                return res
        except ImportError:
            pass
        return {
            "rule_id": rule_id,
            "violation_code": rule_id,
            "severity": "required",
            "summary": "MOF L0 架构约束规则",
            "remediation": "请遵循 L0 架构规范，使用标准 Agora 契约路由",
        }

    @staticmethod
    def _build_diagnostic(v: Any) -> dict[str, Any]:
        diag: dict[str, Any] = {
            "status": "REJECTED",
            "error_type": "MOF_CONSTRAINT_VIOLATION",
            "violation": {
                "rule_id": getattr(v, "rule_id", "X1-C01"),
                "violation_code": getattr(v, "violation_code", "E-L0-001"),
                "severity": getattr(v, "severity", "required"),
                "summary": getattr(v, "summary", "MOF 架构约束拦截"),
                "detail": getattr(v, "detail", ""),
                "remediation": getattr(v, "remediation", "请遵循 L0 协议与架构规范"),
                "line_number": getattr(v, "line_number", None),
                "offending_symbol": getattr(v, "offending_symbol", None),
            },
        }
        patch = getattr(v, "suggested_patch", None)
        if patch is not None:
            diag["violation"]["suggested_patch"] = patch
        return diag


# ── Standalone Fallbacks ──


class _FallbackAstInspector:
    def __init__(self) -> None:
        self.disallowed = {"l4_kernel.internal", "runtime.private", "ecos.internal"}

    def inspect_code(self, source_code: str, caller_layer: str = "L3") -> list[Any]:
        violations = []
        if caller_layer not in ("L3", "L2"):
            return violations
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return violations

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if self._matches(alias.name):
                        violations.append(
                            _SimpleViolation(
                                "X1-C02",
                                "E-L0-002",
                                "跨层直连私有模块违规",
                                f"直接导入了 '{alias.name}'",
                                "请改用 agora.client 统一路由",
                                getattr(node, "lineno", None),
                                alias.name,
                            )
                        )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and self._matches(node.module)
            ):
                violations.append(
                    _SimpleViolation(
                        "X1-C02",
                        "E-L0-002",
                        "跨层直连私有模块违规",
                        f"从 '{node.module}' 导入了符号",
                        "请改用 agora.client 统一路由",
                        getattr(node, "lineno", None),
                        node.module,
                    )
                )
        return violations

    def _matches(self, name: str) -> bool:
        return any(name == d or name.startswith(f"{d}.") for d in self.disallowed)


class _FallbackPathInspector:
    def inspect_write(self, target_path: str, caller_domain: str = "default") -> Any:
        norm = Path(target_path).as_posix().lstrip("./")
        if norm.startswith("@工作文档") and caller_domain != "work-weijian":
            return _SimpleEvalResult(
                False,
                [
                    _SimpleViolation(
                        "X1-C03",
                        "E-L0-003",
                        "跨域越权写入受保护目录",
                        f"Domain '{caller_domain}' 试图写入 '{target_path}'",
                        "请确保具备权限或通过 Agora 注册入口写入",
                        None,
                        target_path,
                    )
                ],
            )
        return _SimpleEvalResult(True, [])


class _FallbackCommandInspector:
    def inspect_command(self, command_line: str) -> Any:
        if re.search(
            r"\bpip\s+install\s+(-g|--global|--user)\b", command_line, re.IGNORECASE
        ):
            return _SimpleEvalResult(
                False,
                [
                    _SimpleViolation(
                        "X1-C01",
                        "E-CMD-001",
                        "禁止全局安装 Python 包",
                        "命令包含全局安装标志",
                        "请使用 uv 或虚拟环境",
                        None,
                        command_line,
                    )
                ],
            )
        if re.search(r"\bport\s*=\s*(8000|8080|9000)\b", command_line, re.IGNORECASE):
            return _SimpleEvalResult(
                False,
                [
                    _SimpleViolation(
                        "X1-C01",
                        "E-CMD-003",
                        "禁止硬编码系统保留端口",
                        "命令包含硬编码保留端口",
                        "请使用动态端口配置",
                        None,
                        command_line,
                    )
                ],
            )
        return _SimpleEvalResult(True, [])


@dataclass
class _SimpleViolation:
    rule_id: str
    violation_code: str
    summary: str
    detail: str
    remediation: str
    line_number: int | None
    offending_symbol: str | None
    severity: str = "required"


@dataclass
class _SimpleEvalResult:
    passed: bool
    violations: list[Any]
