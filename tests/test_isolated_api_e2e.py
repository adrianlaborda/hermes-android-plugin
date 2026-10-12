import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from gateway.config import PlatformConfig
from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.platforms.api_server import APIServerAdapter
from hermes_android.adapter import HermesAndroidAdapter, register


class FakeFcm:
    async def send(self, token, event_id, device_id=""): return "success"


class Context:
    def register_platform(self, **kwargs):
        self.kwargs = kwargs
        platform_registry.register(PlatformEntry(source="builtin", **kwargs))


@pytest.mark.asyncio
async def test_isolated_upstream_api_plugin_flow(tmp_path):
    home = set_hermes_home_override(str(tmp_path))
    context = Context(); register(context)
    android = HermesAndroidAdapter(PlatformConfig(enabled=True, extra={"rpc_secret": "test-plugin-secret-01234567890123456789"}))
    android._transport = FakeFcm()
    api = APIServerAdapter(PlatformConfig(enabled=True, extra={"key": "test-api-key-012345"}))
    app = web.Application()
    app["api_server_adapter"] = api
    app["platform_event_adapters"] = {"hermes_android": android}
    app.router.add_get("/health", api._handle_health)
    app.router.add_get("/v1/capabilities", api._handle_capabilities)
    app.router.add_post("/api/platforms/{platform}/events", api._handle_platform_event_callback)
    try:
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/health")).status == 200
            assert (await client.get("/v1/capabilities", headers={"Authorization": "Bearer test-api-key-012345"})).status == 200
            unauthenticated = await client.post("/api/platforms/hermes_android/events", json={"protocol_version": 1, "type": "device.register"})
            assert unauthenticated.status == 401
            registered = await client.post("/api/platforms/hermes_android/events", headers={"Authorization": "Bearer test-plugin-secret-01234567890123456789"}, json={
                "protocol_version": 1, "type": "device.register", "push": {"type": "fcm", "token": "test-token"}})
            body = await registered.json()
            assert registered.status == 200 and body["ok"] is True
            device = body["result"]
            event = android.store.create_event(device_id=device["device_id"], event_type="reminder", title="test", body="synthetic")
            fetched = await client.post("/api/platforms/hermes_android/events", headers={"Authorization": "Bearer test-plugin-secret-01234567890123456789"}, json={
                "protocol_version": 1, "type": "event.get", "device_id": device["device_id"], "device_secret": device["device_secret"], "event_id": event["event_id"]})
            assert (await fetched.json())["result"]["body"] == "synthetic"
            acked = await client.post("/api/platforms/hermes_android/events", headers={"Authorization": "Bearer test-plugin-secret-01234567890123456789"}, json={
                "protocol_version": 1, "type": "event.ack", "device_id": device["device_id"], "device_secret": device["device_secret"], "event_id": event["event_id"]})
            assert (await acked.json())["result"]["state"] == "acked"
            pending = await client.post("/api/platforms/hermes_android/events", headers={"Authorization": "Bearer test-plugin-secret-01234567890123456789"}, json={
                "protocol_version": 1, "type": "events.pending", "device_id": device["device_id"], "device_secret": device["device_secret"]})
            assert (await pending.json())["result"]["events"] == []
    finally:
        platform_registry.unregister("hermes_android")
        reset_hermes_home_override(home)
