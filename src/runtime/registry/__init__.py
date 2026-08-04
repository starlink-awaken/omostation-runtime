"""Agent Registry — unified multi-machine agent coordination.

HTTP contract notes:
- POST /tasks returns fallback outcomes (dispatched / escalated / pending),
  never assignment internals. Task-to-agent ownership is read via
  GET /tasks assignments. See ADR-0368 for the TaskFallback response
  contract that the registry tests align to.
"""

from .dispatch import Dispatcher, TaskAssignment, TaskRequest, TaskStatus
from .heartbeat import HeartbeatManager
from .models import AgentInfo, AgentStatus, Capability, NodeInfo, NodeRole
from .server import create_app
from .store import RegistryStore
from .sync import GossipSync, Peer, SyncResult

__all__ = [
    "AgentInfo",
    "AgentStatus",
    "Capability",
    "Dispatcher",
    "GossipSync",
    "HeartbeatManager",
    "NodeInfo",
    "NodeRole",
    "Peer",
    "RegistryStore",
    "SyncResult",
    "TaskAssignment",
    "TaskRequest",
    "TaskStatus",
    "create_app",
]
