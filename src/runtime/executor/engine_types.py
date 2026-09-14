"""Engine-specific type definitions for agent-runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SovereigntyLevel(StrEnum):
    FULL = "FULL"
    CONDITIONAL = "CONDITIONAL"
    OBSERVE = "OBSERVE"


@dataclass
class AgentCapability:
    id: str
    description: str = ""


@dataclass
class AgentIdentity:
    id: str
    name: str
    role: str
    sovereignty_level: SovereigntyLevel = SovereigntyLevel.CONDITIONAL
    capabilities: list[AgentCapability] = field(default_factory=list)
    personality: str | None = None
    communication_style: str | None = None
    boundaries: list[str] = field(default_factory=list)


@dataclass
class IdentityValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class WorkingMemoryEntry:
    value: Any
    expires_at: float | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class ProjectMemoryEntry:
    id: str
    project_id: str
    category: str
    key: str
    value: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class OrgMemoryEntry:
    id: str
    category: str
    key: str
    value: str
    source_project: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0


class ErrorSeverity(StrEnum):
    RECOVERABLE = "recoverable"
    NON_RECOVERABLE = "non-recoverable"
    FATAL = "fatal"


class ErrorCategory(StrEnum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    DATABASE = "database"
    CONFIGURATION = "configuration"
    VALIDATION = "validation"
    AGENT_EXECUTION = "agent-execution"
    RESOURCE_EXHAUSTED = "resource-exhausted"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    PLUGIN = "plugin"
    UNKNOWN = "unknown"


@dataclass
class RecoveryStrategy:
    category: ErrorCategory
    severity: ErrorSeverity = ErrorSeverity.RECOVERABLE
    max_retries: int = 3
    base_delay_ms: float = 1000.0
    max_delay_ms: float = 10000.0
    use_exponential_backoff: bool = True
    jitter_factor: float = 0.1
    log_as_warning: bool = True


# fmt: off
class EngineError(Exception):
    def __init__(self, message, category=ErrorCategory.UNKNOWN, severity=ErrorSeverity.NON_RECOVERABLE, retryable=False, context=None, original=None):
        super().__init__(message); self.category = category; self.severity = severity
        self.retryable = retryable; self.context = context or {}; self.original = original
        self.timestamp = time.time()
    @classmethod
    def network(cls, msg, **kw): return cls(msg, ErrorCategory.NETWORK, ErrorSeverity.RECOVERABLE, True, kw)
    @classmethod
    def configuration(cls, msg, **kw): return cls(msg, ErrorCategory.CONFIGURATION, ErrorSeverity.NON_RECOVERABLE, False, kw)
    @classmethod
    def database(cls, msg, retryable=False, **kw):
        sev = ErrorSeverity.RECOVERABLE if retryable else ErrorSeverity.NON_RECOVERABLE
        return cls(msg, ErrorCategory.DATABASE, sev, retryable, kw)
    @classmethod
    def fatal(cls, msg, **kw): return cls(msg, ErrorCategory.UNKNOWN, ErrorSeverity.FATAL, False, kw)
    @classmethod
    def from_exception(cls, exc, **kw):
        m = str(exc)
        if any(x in m for x in ("ECONNREFUSED", "ETIMEDOUT", "ENOTFOUND")): return cls.network(m, original=exc)
        if any(x in m for x in ("ENOENT", "EACCES")): return cls(m, ErrorCategory.FILESYSTEM, ErrorSeverity.NON_RECOVERABLE, False, kw, exc)
        return cls(m, ErrorCategory.UNKNOWN, ErrorSeverity.NON_RECOVERABLE, False, kw, exc)
# fmt: on


class PluginType(StrEnum):
    PROTOCOL = "protocol"
    DECOMPOSER = "decomposer"
    CONTRACT = "contract"
    OBSERVABILITY = "observability"
    STORAGE = "storage"
    NOTIFICATION = "notification"
    AUTH = "auth"
    AGENT = "agent"
    SKILL = "skill"
    INTEGRATION = "integration"
    CUSTOM = "custom"


class PluginStatus(StrEnum):
    REGISTERED = "registered"
    LOADED = "loaded"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    UNLOADED = "unloaded"


PluginPermission = str


@dataclass
class PluginMetadata:
    plugin_id: str
    name: str
    type: PluginType = PluginType.CUSTOM
    version: str = "1.0.0"
    description: str = ""
    author: str | None = None
    dependencies: list[str] = field(default_factory=list)
    permissions: list[PluginPermission] = field(default_factory=list)
    sandbox_enabled: bool = True


@dataclass
class PluginManifest:
    metadata: PluginMetadata
    main: str = ""


@dataclass
class PluginLoadResult:
    plugin_id: str
    success: bool
    error: str | None = None


@dataclass
class PluginStateInfo:
    plugin_id: str
    status: PluginStatus
    last_state_change: float = 0.0
    error: str | None = None
    started_at: float | None = None


@dataclass
class PluginSandboxConfig:
    enabled: bool = True
    allow_read_paths: list[str] = field(default_factory=list)
    allow_write_paths: list[str] = field(default_factory=list)
    deny_paths: list[str] = field(default_factory=lambda: ["/etc", "/sys", "/proc", "/root"])
    allow_network: bool = False
    allow_domains: list[str] = field(default_factory=list)
    allow_spawn: bool = False
    allow_commands: list[str] = field(default_factory=list)
    max_memory_mb: int = 512
    max_cpu_percent: int = 50
    max_execution_time_ms: int = 30000


# fmt: on


# fmt: off
@dataclass
class CompletionOptions:
    model: str | None = None; max_tokens: int | None = None
    temperature: float | None = None; top_p: float | None = None
    system_prompt: str | None = None; stop_sequences: list[str] | None = None
    timeout_ms: int | None = None; api_key: str | None = None; skip_cache: bool = False
    metadata: dict[str, str] | None = None

@dataclass
class CompletionResult:
    content: str; model: str; provider: str
    input_tokens: int = 0; output_tokens: int = 0; total_tokens: int = 0
    finish_reason: str = "stop"; cached: bool = False; duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class CompletionRequest:
    id: str; prompt: str; options: CompletionOptions | None = None

@dataclass
class CompletionChunk:
    delta: str = ""; done: bool = False; input_tokens: int = 0; output_tokens: int = 0

@dataclass
class ProviderConfig:
    name: str; provider_type: str; default_model: str
    supported_models: list[str] = field(default_factory=list)
    max_tokens: int = 128000; supports_streaming: bool = True
    supports_tools: bool = True; supports_batch: bool = False
    timeout_ms: int = 60000; max_retries: int = 3

@dataclass
class CacheConfig:
    enabled: bool = True; max_size: int = 1000; ttl_ms: int = 3_600_000

@dataclass
class RateLimitConfig:
    enabled: bool = True; requests_per_minute: int = 60

@dataclass
class AgentDefinition:
    name: str; description: str = ""
    capabilities: list[str] = field(default_factory=list)
    identity: AgentIdentity | None = None
# fmt: on
