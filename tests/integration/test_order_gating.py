from services.orchestrator.src.orders.order_gate import OrderGate


def test_order_gate_blocks_missing_rules():
    gate = OrderGate(["leading_red", "momentum_flip", "pattern"])
    snapshot = {"leading_red": True, "momentum_flip": False, "pattern": True}
    assert gate.allow(snapshot) is False


def test_order_gate_allows_all_rules_passed():
    gate = OrderGate(["leading_red", "momentum_flip"])
    snapshot = {"leading_red": True, "momentum_flip": True}
    assert gate.allow(snapshot)
