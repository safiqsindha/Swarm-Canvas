from swarm_canvas.comms import DocLog, NoComms, SwarmChatComms
from swarm_canvas.supplier import Supplier
from swarm_canvas.validate import validate_action


def test_color_arrives_next_round_for_requester_only():
    supplier = Supplier(["O", "R", "Gy", "L"], swarm_budget=4)
    grant = supplier.request("a1", "O", 1)
    assert grant["type"] == "grant"
    assert supplier.deliveries(1) == {}
    assert supplier.deliveries(2)["a1"] == ["O"]
    assert "a2" not in supplier.held or "O" not in supplier.held.get("a2", set())
    assert "O" in supplier.held["a1"]


def test_fifth_swarm_request_is_denied():
    supplier = Supplier(["O", "R", "Gy", "L"], swarm_budget=4)
    for color in ["O", "R", "Gy", "L"]:
        assert supplier.request("a1", color, 1)["type"] == "grant"
    denied = supplier.request("a2", "O", 1)
    assert denied["type"] == "deny"
    assert denied["reason"] == "swarm_budget"


def test_third_message_dropped_acks_do_not_count():
    log = DocLog(messages_per_round=2, max_chars=200)
    assert log.post("a1", "one", 1) == 1
    assert log.post("a1", "two", 1) == 2
    assert log.post("a1", "three", 1) is None
    assert log.ack("a1", 1, 1) == 3
    assert "✓ a1 read #1" in log.lines[-1].text
    assert log.post("a1", "next round", 2) == 4

    prepared = validate_action(
        handle="a1",
        action={"messages": ["one", "two", "three"], "acks": [1]},
        round_num=2,
        palette=["S"],
        paint_budget=8,
        comms_enabled=True,
        max_messages=2,
        max_chars=200,
    )
    assert prepared.messages == ["one", "two"]
    assert any(item.get("reason") == "cap" for item in prepared.rejections)
    assert prepared.acks == [1]


def test_ack_of_missing_line_is_rejected():
    log = DocLog()
    log.post("a1", "hello", 1)
    assert log.ack("a1", 99, 1) == 0
    assert len(log.lines) == 1


def test_exposure_lists_exactly_the_inbox_lines():
    log = DocLog(inbox_context_lines=20)
    log.post("a1", "alpha", 1)
    log.post("a2", "beta", 1)
    shown = log.inbox("slot-2", 2)
    assert log.exposure["slot-2"] == [line.number for line in shown]
    assert log.exposure["slot-2"] == [1, 2]
    again = log.inbox("slot-2", 3)
    assert [line.number for line in again] == log.exposure["slot-2"]


def test_nocomms_and_swarmchat_cap():
    quiet = NoComms()
    assert quiet.post("a1", "hi", 1) is None
    assert quiet.inbox("slot-0", 1) == []
    assert quiet.exposure["slot-0"] == []

    chat = SwarmChatComms(server_url="", messages_per_round=2)
    assert chat.post("a1", "one", 1) == 1
    assert chat.post("a1", "two", 1) == 2
    assert chat.post("a1", "three", 1) is None
    assert chat.ack("a1", 1, 1) == 3
    assert chat.remote_errors == []
