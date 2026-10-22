import base64
import json
import os
import stat

import pytest
from hermes_constants import reset_hermes_home_override, set_hermes_home_override

from hermes_android import setup, tools

KEY = {"type": "service_account", "project_id": "demo-proj", "client_email": "sender@demo-proj.iam.gserviceaccount.com",
       "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in ("HERMES_ANDROID_RPC_SECRET", "API_SERVER_ENABLED", "API_SERVER_HOST", "API_SERVER_PORT"):
        monkeypatch.delenv(name, raising=False)
    token = set_hermes_home_override(str(tmp_path))
    try:
        yield tmp_path
    finally:
        reset_hermes_home_override(token)


def test_validate_rejects_app_config_and_partial_keys():
    with pytest.raises(ValueError, match="google-services.json"):
        setup.validate_service_account({"project_info": {}, "client": []})
    with pytest.raises(ValueError, match="private_key"):
        setup.validate_service_account({**KEY, "private_key": ""})
    assert setup.validate_service_account(KEY) == {"project_id": "demo-proj", "client_email": KEY["client_email"]}


def test_configure_creates_secret_without_returning_it(home):
    result = setup.configure()
    env = (home / ".env").read_text()
    secret = env.split("HERMES_ANDROID_RPC_SECRET=", 1)[1].splitlines()[0]
    assert len(secret) >= 32
    assert secret not in json.dumps(result)
    assert result["restart_required"] and "pairing secret created" in result["changed"]
    again = setup.configure()
    assert "pairing secret created" not in again["changed"]


def test_upload_installs_owner_only_key_and_points_config(home):
    encoded = base64.b64encode(json.dumps(KEY).encode()).decode()
    result = setup.install_credentials_upload(encoded)
    target = home / "credentials" / "hermes-android" / "fcm-service-account.json"
    assert result == {"installed": str(target), "project_id": "demo-proj"}
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert json.loads(target.read_text()) == KEY
    state = setup._credentials_state()
    assert state["state"] == "ok" and state["project_id"] == "demo-proj"
    assert "private_key" not in json.dumps(setup.status())


def test_install_from_server_path_deletes_the_copy(home, tmp_path):
    source = tmp_path / "upload.json"
    source.write_text(json.dumps(KEY))
    result = setup.install_credentials(str(source))
    assert result["source_deleted"] and not source.exists()


def test_pairing_needs_api_server_and_secret(home, monkeypatch):
    monkeypatch.setattr(setup, "_api_server", lambda: {"enabled": False, "host": "127.0.0.1", "port": 8642,
                                                       "reachable_from_phone": False})
    payload = setup.pairing_payload()
    assert payload["ready"] is False and "secret" not in payload and payload["problem"] == "api_server_disabled"
    setup.configure()
    monkeypatch.setattr(setup, "_api_server", lambda: {"enabled": True, "host": "192.168.1.5", "port": 8642,
                                                       "reachable_from_phone": True})
    payload = setup.pairing_payload()
    assert payload["ready"] is True and len(payload["secret"]) >= 32 and payload["hermes_android_pairing"] == 1


def test_secret_bearing_commands_refuse_messaging_channels(home, monkeypatch):
    monkeypatch.setattr(tools, "_is_messaging_surface", lambda: True)
    assert "secret" not in tools.pair_command("")
    assert json.loads(tools.credentials_command("e30="))["ok"] is False
    assert json.loads(tools.enable_command("work"))["ok"] is False


@pytest.mark.parametrize("source, messaging", [("telegram", True), ("whatsapp", True), ("mobile", False),
                                               ("desktop", False), ("tui", False), ("", False)])
def test_the_app_is_not_a_messaging_surface(monkeypatch, source, messaging):
    from gateway import session_context
    monkeypatch.delenv("HERMES_PLATFORM", raising=False)
    monkeypatch.setattr(session_context, "get_session_env",
                        lambda name, default="": source if name == "HERMES_SESSION_SOURCE" else default)
    assert tools._is_messaging_surface() is messaging


def test_tool_handlers_wrap_errors_as_json(home):
    handler = dict((schema["name"], handler) for schema, handler, _ in tools.TOOLS)["hermes_android_install_credentials"]
    reply = json.loads(handler({"path": "/nonexistent/key.json"}))
    assert reply["ok"] is False and "No file" in reply["error"]


def test_primary_channel_command_reports_and_toggles(home, monkeypatch):
    import yaml
    monkeypatch.setattr(tools, "_is_messaging_surface", lambda: False)
    (home / "config.yaml").write_text("model: {}\n")
    (home / ".env").write_text("HERMES_ANDROID_RPC_SECRET=" + "s" * 40 + "\n")
    name = setup.profile_name()
    assert json.loads(tools.primary_channel_command("")) == {"primary_channel": True, "profile": name}
    assert json.loads(tools.primary_channel_command("off")) == {"primary_channel": False, "profile": name}
    assert json.loads(tools.primary_channel_command(""))["primary_channel"] is False
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["model"] == {} and config["platforms"]["hermes_android"]["primary_channel"] is False
    assert json.loads(tools.primary_channel_command("on"))["primary_channel"] is True
    # Only the config key changes: the secret file is untouched.
    assert (home / ".env").read_text() == "HERMES_ANDROID_RPC_SECRET=" + "s" * 40 + "\n"


def test_primary_channel_command_targets_another_profile(home, monkeypatch):
    import yaml
    monkeypatch.setenv("HERMES_HOME", str(home))  # profile discovery reads the environment, not the override
    monkeypatch.setattr(tools, "_is_messaging_surface", lambda: False)
    work = home / "profiles" / "work"
    work.mkdir(parents=True)
    (work / "config.yaml").write_text("model: {}\n")
    assert json.loads(tools.primary_channel_command("work off")) == {"primary_channel": False, "profile": "work"}
    assert yaml.safe_load((work / "config.yaml").read_text())["platforms"]["hermes_android"]["primary_channel"] is False
    assert json.loads(tools.primary_channel_command("work")) == {"primary_channel": False, "profile": "work"}
    assert json.loads(tools.primary_channel_command(""))["primary_channel"] is True


def test_primary_channel_command_errors(home, monkeypatch):
    monkeypatch.setattr(tools, "_is_messaging_surface", lambda: False)
    assert "error" in json.loads(tools.primary_channel_command("work maybe"))
    assert "error" in json.loads(tools.primary_channel_command("ghost on"))


def test_primary_channel_write_refused_in_messaging_channels(home, monkeypatch):
    monkeypatch.setattr(tools, "_is_messaging_surface", lambda: True)
    assert "error" in json.loads(tools.primary_channel_command("off"))
    assert not (home / "config.yaml").exists() or "primary_channel" not in (home / "config.yaml").read_text()
    # Reporting stays available in a messaging channel.
    assert json.loads(tools.primary_channel_command(""))["primary_channel"] is True


def test_primary_channel_command_is_registered(monkeypatch):
    names = {}
    class Context:
        def register_command(self, name, handler, description=""):
            names[name] = handler
    tools.register(Context())
    assert names["android-primary-channel"] is tools.primary_channel_command
