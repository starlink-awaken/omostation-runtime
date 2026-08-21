"""Tests for MerkleActionLedger and Cryptographic Proofs (ADR-0201)."""

import pytest

from runtime.merkle_ledger import MerkleActionLedger, sha256


def test_empty_ledger():
    """Verify empty ledger returns valid base root hash."""
    ledger = MerkleActionLedger()
    assert ledger.size == 0
    assert ledger.root_hash == sha256("EMPTY_LEDGER_ROOT")


def test_single_action_record_and_proof():
    """Verify single action record and inclusion proof validation."""
    ledger = MerkleActionLedger()
    entry = ledger.record_action(
        action_id="act-001",
        agent_id="agent-weijian-lead",
        target_uri="bos://governance/policy/enforce",
        args={"domain": "work-weijian", "rule_id": "RULE-DATA-01"},
        policy_passed=True,
    )
    assert ledger.size == 1
    assert ledger.root_hash == entry.compute_leaf_hash()

    proof = ledger.generate_inclusion_proof("act-001")
    assert proof is not None
    assert proof.verify() is True
    assert proof.root_hash == ledger.root_hash


def test_multi_actions_merkle_tree_integrity():
    """Verify multi-action Merkle tree recomputation and tamper detection."""
    ledger = MerkleActionLedger()
    for i in range(7):
        ledger.record_action(
            action_id=f"act-{i:03d}",
            agent_id=f"agent-{i % 3}",
            target_uri=f"bos://capability/tool/{i}",
            args={"step": i, "payload": f"data_{i}"},
            policy_passed=True,
        )

    assert ledger.size == 7

    # 验证每个叶子的包含证明全部有效
    for i in range(7):
        aid = f"act-{i:03d}"
        proof = ledger.generate_inclusion_proof(aid)
        assert proof is not None
        assert proof.verify() is True

    # 模拟篡改数据测试
    tampered_proof = ledger.generate_inclusion_proof("act-003")
    assert tampered_proof is not None
    # 篡改叶子哈希
    tampered_proof.leaf_hash = sha256("FORGED_ACTION_DATA")
    assert tampered_proof.verify() is False
