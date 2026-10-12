import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from gateway.config import PlatformConfig
from gateway.platform_registry import PlatformEntry, platform_registry
from hermes_android.adapter import HermesAndroidAdapter, register, standalone_sender


class FakeFcm:
    def __init__(self, outcome="success"):
        self.outcome, self.calls = outcome, []

    async def send(self, token, event_id, device_id=""):
        self.calls.append((token, event_id))
        return self.outcome


@pytest.fixture
def adapter(tmp_path):
    token = set_hermes_home_override(str(tmp_path))
    platform_registry.register(PlatformEntry(name="hermes_android", label="fixture", adapter_factory=lambda c: None,
                                             check_fn=lambda: True, source="builtin"))
    instance = HermesAndroidAdapter(PlatformConfig(enabled=True, extra={}))
    instance._transport = FakeFcm()
    try:
        yield instance
    finally:
        platform_registry.unregister("hermes_android")
        reset_hermes_home_override(token)


@pytest.mark.asyncio
async def test_rpc_contract_cross_device_and_malformed(adapter):
    first = await adapter.dispatch_http_event({"protocol_version": 1, "type": "device.register", "push": {"type": "fcm", "token": "one"}})
    second = await adapter.dispatch_http_event({"protocol_version": 1, "type": "device.register", "push": {"type": "fcm", "token": "two"}})
    a, b = first["result"], second["result"]
    event = adapter.store.create_event(device_id=a["device_id"], event_type="reminder", title="t", body="private")
    denied = await adapter.dispatch_http_event({"protocol_version": 1, "type": "event.get", "device_id": b["device_id"], "device_secret": b["device_secret"], "event_id": event["event_id"]})
    assert denied["ok"] is False and denied["error"]["code"] == "event_not_found"
    assert (await adapter.dispatch_http_event({"protocol_version": 2, "type": "events.pending"}))["error"]["code"] == "unsupported_protocol"
    assert (await adapter.dispatch_http_event({"protocol_version": 1, "type": "nope"}))["error"]["code"] == "unknown_operation"


@pytest.mark.asyncio
async def test_cron_sender_persists_before_fcm_and_revoke_on_permanent(adapter):
    registered = await adapter.dispatch_http_event({"protocol_version": 1, "type": "device.register", "push": {"type": "fcm", "token": "one"}})
    device = registered["result"]
    result = await adapter.send(device["device_id"], "cron result", metadata={"dedup_key": "job:1"})
    assert result.success and adapter._transport.calls
    with adapter.store._transaction() as conn:
        assert conn.execute("SELECT state FROM events WHERE event_id=?", (result.message_id,)).fetchone()["state"] == "push_sent"
    adapter._transport.outcome = "permanent"
    await adapter.send(device["device_id"], "bad token")
    assert (await adapter.dispatch_http_event({"protocol_version": 1, "type": "events.pending", "device_id": device["device_id"], "device_secret": device["device_secret"]}))["error"]["code"] == "device_revoked"


def test_registration_declares_only_existing_platform_seams():
    captured = {}
    class Context:
        def register_platform(self, **kwargs): captured.update(kwargs)
    register(Context())
    assert captured["name"] == "hermes_android"
    assert "http_event_auth_mode" not in captured
    assert callable(captured["standalone_sender_fn"])


def test_upstream_verifier_fails_closed(adapter):
    assert adapter.verify_http_event_request('Bearer anything')[0] is False
    adapter._rpc_secret = 'a' * 40
    assert adapter.verify_http_event_request('Bearer ' + 'a' * 40) == (True, '')
    assert adapter.verify_http_event_request('Basic ' + 'a' * 40)[0] is False
    assert adapter.verify_http_event_request('Bearer ' + 'b' * 40)[0] is False


def test_completion_hook_deduplicates_and_keeps_session_owner(adapter):
    from hermes_android.hooks import on_session_end
    device = adapter.store.register(device_id=None, device_secret=None, label='test', push_type='fcm', push_token='test')
    on_session_end(session_id='session-a', turn_id='turn-b', completed=True)
    on_session_end(session_id='session-a', turn_id='turn-b', completed=True)
    on_session_end(session_id='session-a', turn_id='turn-c', interrupted=True)
    events = adapter.store.pending(device['device_id'], device['device_secret'])
    assert len(events) == 1 and events[0]['session_id'] == 'session-a'
