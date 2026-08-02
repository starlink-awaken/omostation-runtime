"""E2E integration test: two GossipSync instances sync via real uvicorn servers.

Spins up two FastAPI apps on different ports using uvicorn, registers agents
on one, forces cross-node sync, and verifies state convergence.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import uvicorn

from runtime.registry.server import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    """Wraps a uvicorn server in a thread for testing."""

    def __init__(self, port: int, node_id: str):
        self.port = port
        self.node_id = node_id
        self.app = create_app(persist_path=None, node_id=node_id)
        self._config = uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self):
        self._thread.start()
        self._wait_ready()

    def _wait_ready(self, timeout=5):
        import httpx
        url = f"http://127.0.0.1:{self.port}/health"
        for _ in range(int(timeout * 20)):
            try:
                if httpx.get(url, timeout=0.1).status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.05)

    def stop(self):
        self._server.should_exit = True
        self._thread.join(timeout=2)


@pytest.fixture
def two_nodes():
    """Start two real registry servers on different ports.

    Scoped per-test so each test gets fresh in-memory stores.
    """
    port_a = _free_port()
    port_b = _free_port()

    node_a = _Server(port_a, "node-a")
    node_b = _Server(port_b, "node-b")
    node_a.start()
    node_b.start()

    yield node_a, node_b

    node_a.stop()
    node_b.stop()


class TestGossipSyncTwoNodeE2E:
    """End-to-end two-node sync verification."""

    def test_register_on_a_visible_on_b(self, two_nodes):
        """Register agent on node-a, sync, verify visible on node-b."""
        import httpx

        node_a, node_b = two_nodes
        base_a = f"http://127.0.0.1:{node_a.port}"
        base_b = f"http://127.0.0.1:{node_b.port}"

        with httpx.Client(timeout=5) as c:
            # Verify both start empty
            assert len(c.get(f"{base_b}/agents").json()) == 0

            # Register agent on node-a
            resp = c.post(f"{base_a}/agents", json={
                "name": "shared-worker",
                "node_id": "node-a",
                "endpoint": f"{base_a}/agents/shared-worker",
                "capabilities": [{"name": "python", "tags": [], "cost_eu": 0.0}],
                "max_concurrency": 2,
            })
            assert resp.status_code == 201

            # Add peers BEFORE any background sync can interfere
            c.post(f"{base_a}/peers", json={"host": "127.0.0.1", "port": node_b.port})
            c.post(f"{base_b}/peers", json={"host": "127.0.0.1", "port": node_a.port})

            # Force sync on node-a (pulls from node-b, pushes to node-b)
            r_a = c.post(f"{base_a}/sync/force")
            assert r_a.status_code == 200
            result_a = r_a.json()
            assert result_a["pushed"] > 0

            # Verify agent now visible on node-b
            resp_b = c.get(f"{base_b}/agents")
            agents_b = resp_b.json()
            assert len(agents_b) >= 1
            assert any(a["name"] == "shared-worker" for a in agents_b)

    def test_bidirectional_sync(self, two_nodes):
        """Register agents on both nodes, sync both ways → each sees both."""
        import httpx

        node_a, node_b = two_nodes
        base_a = f"http://127.0.0.1:{node_a.port}"
        base_b = f"http://127.0.0.1:{node_b.port}"

        with httpx.Client(timeout=5) as c:
            # Register different agents on each node
            c.post(f"{base_a}/agents", json={
                "name": "worker-a",
                "node_id": "node-a",
                "capabilities": [{"name": "coding", "tags": [], "cost_eu": 0.0}],
            })
            c.post(f"{base_b}/agents", json={
                "name": "worker-b",
                "node_id": "node-b",
                "capabilities": [{"name": "review", "tags": [], "cost_eu": 0.0}],
            })

            # Add peers
            c.post(f"{base_a}/peers", json={"host": "127.0.0.1", "port": node_b.port})
            c.post(f"{base_b}/peers", json={"host": "127.0.0.1", "port": node_a.port})

            # Sync both directions
            c.post(f"{base_a}/sync/force")
            c.post(f"{base_b}/sync/force")

            # Each node should see 2 agents
            agents_a = c.get(f"{base_a}/agents").json()
            agents_b = c.get(f"{base_b}/agents").json()

            assert len(agents_a) == 2
            assert len(agents_b) == 2

            names_a = {a["name"] for a in agents_a}
            names_b = {a["name"] for a in agents_b}
            assert "worker-a" in names_a
            assert "worker-b" in names_a
            assert "worker-a" in names_b
            assert "worker-b" in names_b

    def test_failover_node_redistributes_tasks(self, two_nodes):
        """When a node fails, tasks are redistributed to the surviving node."""
        import httpx

        node_a, node_b = two_nodes
        base_a = f"http://127.0.0.1:{node_a.port}"
        base_b = f"http://127.0.0.1:{node_b.port}"

        with httpx.Client(timeout=5) as c:
            # Register agents on both nodes with same capability
            c.post(f"{base_a}/agents", json={
                "name": "node-a-worker",
                "node_id": "node-a",
                "capabilities": [{"name": "compute", "tags": [], "cost_eu": 0.0}],
            })
            c.post(f"{base_b}/agents", json={
                "name": "node-b-worker",
                "node_id": "node-b",
                "capabilities": [{"name": "compute", "tags": [], "cost_eu": 0.0}],
            })

            # Submit task to node-a
            task_resp = c.post(f"{base_a}/tasks", json={
                "name": "critical-job",
                "required_capabilities": ["compute"],
            })
            assert task_resp.status_code == 201
            assert task_resp.json()["status"] == "dispatched"
            task_id = task_resp.json()["task_id"]

            # Failover node-a (the node that got the task)
            fail_resp = c.post(f"{base_a}/failover/node-a")
            assert fail_resp.status_code == 200
            # Task should be reassigned to node-b's worker
            assert fail_resp.json()["redispatched"] >= 1
