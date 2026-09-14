"""Cryptographic Merkle Action Ledger & Compliance Sandbox (ADR-0201).

Provides tamper-evident cryptographic provenance and Merkle Inclusion Proofs
for Agent actions across external interfaces and state transitions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import Any


def sha256(data: str | bytes) -> str:
    """Compute SHA-256 hex digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass
class ActionEntry:
    """可验证操作条目."""

    action_id: str
    agent_id: str
    target_uri: str
    args: dict[str, Any]
    policy_passed: bool
    policy_verifier: str = "shadow-challenger"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_leaf_hash(self) -> str:
        """计算操作叶子节点的唯一确定性哈希."""
        args_canonical = json.dumps(self.args, sort_keys=True, separators=(",", ":"))
        raw = f"{self.action_id}|{self.timestamp}|{self.agent_id}|{self.target_uri}|{sha256(args_canonical)}|{self.policy_passed}|{self.policy_verifier}"
        return sha256(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "agent_id": self.agent_id,
            "target_uri": self.target_uri,
            "args": self.args,
            "policy_passed": self.policy_passed,
            "policy_verifier": self.policy_verifier,
            "timestamp": self.timestamp,
            "leaf_hash": self.compute_leaf_hash(),
            "metadata": self.metadata,
        }


@dataclass
class MerkleInclusionProof:
    """Merkle 包含证明 (Inclusion Proof)."""

    action_id: str
    leaf_hash: str
    leaf_index: int
    tree_size: int
    audit_path: list[dict[str, str]]  # [{"direction": "left"|"right", "hash": "..."}]
    root_hash: str

    def verify(self) -> bool:
        """验证该证明在当前 root_hash 下是否数学成立."""
        current = self.leaf_hash
        for step in self.audit_path:
            sibling = step["hash"]
            if step["direction"] == "left":
                current = sha256(sibling + current)
            else:
                current = sha256(current + sibling)
        return current == self.root_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "leaf_hash": self.leaf_hash,
            "leaf_index": self.leaf_index,
            "tree_size": self.tree_size,
            "audit_path": self.audit_path,
            "root_hash": self.root_hash,
        }


class MerkleActionLedger:
    """密码学级操作审计账本 (Merkle Action Ledger)."""

    def __init__(self) -> None:
        self.entries: list[ActionEntry] = []
        self._leaves: list[str] = []
        self._root_hash: str = sha256("EMPTY_LEDGER_ROOT")

    @property
    def root_hash(self) -> str:
        return self._root_hash

    @property
    def size(self) -> int:
        return len(self.entries)

    def record_action(
        self,
        action_id: str,
        agent_id: str,
        target_uri: str,
        args: dict[str, Any],
        policy_passed: bool = True,
        policy_verifier: str = "shadow-challenger",
        metadata: dict[str, Any] | None = None,
    ) -> ActionEntry:
        """记录一条操作并增量更新 Merkle 树."""
        entry = ActionEntry(
            action_id=action_id,
            agent_id=agent_id,
            target_uri=target_uri,
            args=args,
            policy_passed=policy_passed,
            policy_verifier=policy_verifier,
            metadata=metadata or {},
        )
        self.entries.append(entry)
        self._leaves.append(entry.compute_leaf_hash())
        self._recompute_tree()
        return entry

    def _recompute_tree(self) -> None:
        """重算 Merkle 根哈希."""
        if not self._leaves:
            self._root_hash = sha256("EMPTY_LEDGER_ROOT")
            return

        current_layer = self._leaves
        while len(current_layer) > 1:
            next_layer = []
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                right = current_layer[i + 1] if i + 1 < len(current_layer) else left
                next_layer.append(sha256(left + right))
            current_layer = next_layer
        self._root_hash = current_layer[0]

    def generate_inclusion_proof(self, action_id: str) -> MerkleInclusionProof | None:
        """为指定 action_id 生成 Merkle Inclusion Proof."""
        index = next((i for i, e in enumerate(self.entries) if e.action_id == action_id), None)
        if index is None:
            return None

        audit_path: list[dict[str, str]] = []
        current_layer = list(self._leaves)
        curr_idx = index

        while len(current_layer) > 1:
            is_odd = curr_idx % 2 == 1
            sibling_idx = curr_idx - 1 if is_odd else (curr_idx + 1 if curr_idx + 1 < len(current_layer) else curr_idx)
            sibling_hash = current_layer[sibling_idx]

            audit_path.append(
                {
                    "direction": "left" if is_odd else "right",
                    "hash": sibling_hash,
                }
            )

            # 向上推进一层
            next_layer = []
            for i in range(0, len(current_layer), 2):
                l = current_layer[i]
                r = current_layer[i + 1] if i + 1 < len(current_layer) else l
                next_layer.append(sha256(l + r))
            current_layer = next_layer
            curr_idx = curr_idx // 2

        return MerkleInclusionProof(
            action_id=action_id,
            leaf_hash=self._leaves[index],
            leaf_index=index,
            tree_size=len(self.entries),
            audit_path=audit_path,
            root_hash=self._root_hash,
        )

    def export_summary(self) -> dict[str, Any]:
        """导出账本摘要."""
        return {
            "size": self.size,
            "root_hash": self.root_hash,
            "latest_timestamp": self.entries[-1].timestamp if self.entries else None,
            "latest_action_id": self.entries[-1].action_id if self.entries else None,
        }
