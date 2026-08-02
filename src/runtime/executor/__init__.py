"""Agent Runtime — multi-agent orchestration engine.

The public class is loaded lazily so low-level modules such as the append-only
effect journal can import without recursively importing the execution engine.
"""

__version__ = "0.5.0"
__all__ = (
    "AgentRuntime",
    "__version__",
)


def __getattr__(name: str):
    if name == "AgentRuntime":
        from runtime.executor.engine import AgentRuntime

        return AgentRuntime
    raise AttributeError(name)
