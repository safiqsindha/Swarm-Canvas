"""Integration tests run against the actual pinned SwarmChat server, not an HTTP imitation."""

import httpx
import pytest
from swarmchat.config import load
from swarmchat.store import Store

from swarm_canvas.comms import SwarmChatComms
from swarm_canvas.swarmchat_native import SwarmChatError


@pytest.fixture
def native(tmp_path):
    comms = SwarmChatComms(agent_ids=["slot-0", "slot-1"], data_dir=tmp_path / "server")
    try:
        yield comms
    finally:
        comms.close()


def test_inbox_reads_native_messages_missing_from_audit_cache(native):
    message = native.clients["slot-0"].send(chat=native.channel_id, text="native-only")[
        "message"
    ]
    assert native.lines == []
    lines = native.inbox("slot-1", 2)
    assert [line.text for line in lines] == ["native-only"]
    assert lines[0].remote_id == message["id"]
    assert native.native_read["slot-1"] == [message["seq"]]
    sender_view = native.inbox("slot-0", 3)
    assert sender_view[0].read_by == ["slot-1"]


def test_round_freezes_messages_and_read_receipts_for_all_painters(native):
    number = native.post("slot-0", "hello", 1)
    native.begin_round(2)
    native.inbox("slot-1", 2)
    sender_round2 = native.inbox("slot-0", 2)
    assert (
        sender_round2[0].read_by == []
    )  # same snapshot, despite receiver being observed first
    assert native.inbox("slot-0", 3)[0].read_by == ["slot-1"]
    native.begin_round(4)
    native.post("slot-0", "later in round four", 4)
    assert [line.number for line in native.inbox("slot-1", 4)] == [number]
    assert [line.text for line in native.inbox("slot-1", 5)] == [
        "hello",
        "later in round four",
    ]


def test_remote_adapter_authenticates_and_isolates_private_run_channels(native):
    tokens = {agent: client.token for agent, client in native.clients.items()}
    remote = SwarmChatComms(
        agent_ids=native.agent_ids, server_url=native.server_url, tokens=tokens
    )
    try:
        assert remote.channel_id != native.channel_id
        assert remote.metadata()["transport"] == "native_remote"
        remote.post("slot-0", "private experiment", 1)
        assert native.inbox("slot-1", 2) == []
        assert remote.inbox("slot-1", 2)[0].text == "private experiment"
        info = remote.clients["slot-1"].chat_info(chat=remote.channel_id)["chat"]
        assert info["public"] is False
        assert {m["id"] for m in info["members"]} == {"slot-0", "slot-1"}
    finally:
        remote.close()
    assert (
        native.clients["slot-0"].whoami()["user"]["id"] == "slot-0"
    )  # remote cleanup leaves caller's server intact


def test_duplicate_authenticated_users_are_rejected(native):
    token = native.clients["slot-0"].token
    with pytest.raises(SwarmChatError, match="different SwarmChat user"):
        SwarmChatComms(
            agent_ids=["slot-0", "slot-1"],
            server_url=native.server_url,
            tokens={"slot-0": token, "slot-1": token},
        )


def test_bad_token_fails_without_fallback(native):
    with pytest.raises(SwarmChatError, match="whoami failed"):
        SwarmChatComms(
            agent_ids=["slot-0"],
            server_url=native.server_url,
            tokens={"slot-0": "invalid-token"},
        )


def test_native_caps_and_acks_do_not_create_extra_chat_messages(native):
    first = native.post("slot-0", "a" * 250, 1)
    native.post("slot-0", "second", 1)
    assert native.post("slot-0", "third", 1) is None
    shown = native.inbox("slot-1", 2)
    assert len(shown[0].text) == 200
    assert native.ack("slot-1", first, 2) == first
    assert native.ack("slot-1", 100000, 2) == 0
    messages = native.clients["slot-0"].read(
        chat=native.channel_id, **{"all": True}, peek=True
    )["messages"]
    assert len(messages) == 2
    assert messages[0]["read_by"][0]["id"] == "slot-1"


def test_native_read_positions_persist_after_shutdown(tmp_path):
    data_dir = tmp_path / "server"
    native = SwarmChatComms(agent_ids=["slot-0", "slot-1"], data_dir=data_dir)
    number = native.post("slot-0", "persisted", 1)
    native.inbox("slot-1", 2)
    channel_id = native.channel_id
    url = native.server_url
    native.close()
    native.close()  # idempotent cleanup
    store = Store(str(data_dir), load(data=str(data_dir)), read_only=True)
    try:
        assert store.position("slot-1", store.chats[channel_id]) >= number
        assert store.chats[channel_id].name.startswith("canvas-")
    finally:
        store.close()
    assert url.startswith("http://127.0.0.1:")
    with pytest.raises(httpx.ConnectError):
        httpx.get(url + "/v1/health", timeout=1, trust_env=False)


def test_native_history_pagination_and_context(native):
    native._store.settings["max_page"] = 2
    native.inbox_context_lines = 2
    for number in range(1, 7):
        native.post("slot-0", f"note-{number}", number)
    first = native.inbox("slot-1", 7)
    assert [line.text for line in first] == [f"note-{number}" for number in range(1, 7)]
    context = native.inbox("slot-1", 8)
    assert [line.text for line in context] == ["note-5", "note-6"]


def test_scripted_check_validates_native_receipts_with_no_models(tmp_path):
    from swarm_canvas.swarmchat_check import check_swarmchat

    result = check_swarmchat(output_root=tmp_path)
    assert result["status"] == "passed" and result["model_calls"] == 0
    assert result["messages"] == result["receipt_checks"] == 4


def test_local_recovery_preserves_channel_messages_and_read_positions(tmp_path):
    data = tmp_path / 'native'
    first = SwarmChatComms(agent_ids=['slot-0', 'slot-1'], data_dir=data)
    message = first.post('slot-0', 'hello peer', 1)
    shown = first.inbox('slot-1', 2)
    assert shown[0].number == message
    saved = first.checkpoint_state()
    assert 'token' not in str(saved).lower()
    first.close()
    second = SwarmChatComms(agent_ids=['slot-0', 'slot-1'], data_dir=data,
                            recovery_state=saved)
    try:
        assert second.channel_id == saved['metadata']['channel_id']
        assert second.inbox('slot-1', 3)[0].text == 'hello peer'
        assert second.inbox('slot-0', 3)[0].read_by == ['slot-1']
        assert second.post('slot-1', 'reply', 3) > message
    finally:
        second.close()


def test_recovery_refuses_changed_channel_or_unsafe_token_file(tmp_path):
    data = tmp_path / 'native'
    first = SwarmChatComms(agent_ids=['slot-0', 'slot-1'], data_dir=data)
    first.post('slot-0', 'before', 1)
    saved = first.checkpoint_state()
    first.post('slot-1', 'after boundary', 2)
    first.close()
    with pytest.raises(SwarmChatError, match='differs from the saved boundary'):
        SwarmChatComms(agent_ids=['slot-0', 'slot-1'], data_dir=data, recovery_state=saved)
    (data / 'recovery_tokens.json').chmod(0o644)
    with pytest.raises(SwarmChatError, match='unsafe permissions'):
        SwarmChatComms(agent_ids=['slot-0', 'slot-1'], data_dir=data, recovery_state=saved)


def test_remote_recovery_is_refused_before_network():
    with pytest.raises(ValueError, match='only a local'):
        SwarmChatComms(agent_ids=['slot-0'], server_url='https://example.invalid',
                       recovery_state={})
