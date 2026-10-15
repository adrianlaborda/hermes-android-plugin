import json
import os

import pytest
from hermes_constants import reset_hermes_home_override, set_hermes_home_override

from hermes_android import hooks, setup, tools
from hermes_android.store import DeviceStore

KEY = {"type": "service_account", "project_id": "demo-proj", "client_email": "sender@demo-proj.iam.gserviceaccount.com",
       "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_ANDROID_RPC_SECRET", raising=False)
    token = set_hermes_home_override(str(tmp_path))
    try:
        yield tmp_path
    finally:
        reset_hermes_home_override(token)


@pytest.fixture
def pushed(monkeypatch):
    sent = []
    monkeypatch.setattr(hooks, "_push_soon", lambda ids: sent.extend(ids))
    monkeypatch.setattr(hooks, "_turn_summary", lambda sid: ("Plan the trip", "Here is the itinerary…"))
    return sent


def _device():
    return DeviceStore().register(device_id=None, device_secret=None, label="p", push_type="fcm", push_token="t")


def test_turn_notice_carries_chat_title_and_excerpt(home, pushed):
    device = _device()
    hooks.on_session_end(session_id="s1", turn_id="t1", completed=True, platform="api_server")
    event = DeviceStore().pending(device["device_id"], device["device_secret"])[0]
    assert (event["title"], event["body"], event["session_id"]) == ("Plan the trip", "Here is the itinerary…", "s1")
    assert pushed == [event["event_id"]]


def _set(key, value, home):
    from hermes_cli.config import set_config_value
    set_config_value(key, value)
    # Config readers cache by mtime; two writes within one test can share a timestamp.
    config = home / "config.yaml"
    stamp = os.stat(config).st_mtime_ns + 2_000_000_000
    os.utime(config, ns=(stamp, stamp))


def test_messaging_turns_stay_quiet_unless_configured(home, pushed):
    device = _device()
    hooks.on_session_end(session_id="s1", turn_id="t1", completed=True, platform="telegram")
    assert DeviceStore().pending(device["device_id"], device["device_secret"]) == []
    _set("platforms.hermes_android.notify_turns", "all", home)
    hooks.on_session_end(session_id="s1", turn_id="t2", completed=True, platform="telegram")
    assert len(DeviceStore().pending(device["device_id"], device["device_secret"])) == 1
    _set("platforms.hermes_android.notify_turns", "never", home)
    hooks.on_session_end(session_id="s1", turn_id="t3", completed=True, platform="api_server")
    assert len(DeviceStore().pending(device["device_id"], device["device_secret"])) == 1


def test_excerpt_drops_markup():
    assert hooks._plain("**Done** ✅\n```py\nx=1\n```\nSee [the docs](http://x) ![img](a.png)") == "Done ✅ See the docs"


def test_enable_profile_plans_then_links_with_shared_key(home):
    (home / "profiles" / "work").mkdir(parents=True)
    (home / "profiles" / "work" / "config.yaml").write_text("model: {}\n")
    setup.configure()
    setup.install_credentials_json(KEY)
    plan = setup.enable_for_profile("work")
    assert plan["dry_run"] and any("link the plugin" in step for step in plan["plan"])
    assert not (home / "profiles" / "work" / "plugins" / "hermes-android").exists()
    done = setup.enable_for_profile("work", apply=True)
    work = home / "profiles" / "work"
    link = work / "plugins" / "hermes-android"
    # One install serves every profile: the profile gets a link, not a copy.
    assert link.is_symlink() and link.resolve() == setup._source_dir()
    assert done["now"]["plugin_install"] == "link"
    assert done["now"]["plugin_enabled"] and done["now"]["platform_enabled"]
    assert done["now"]["pairing_secret"] == "ok" and done["now"]["server_key"] == "ok"
    # The key file is shared, never duplicated into the profile.
    assert not (work / "credentials").exists()
    assert "HERMES_ANDROID_RPC_SECRET=" in (work / ".env").read_text()
    # The work profile gets its own secret, not the default one.
    default_secret = (home / ".env").read_text().split("HERMES_ANDROID_RPC_SECRET=")[1].splitlines()[0]
    assert default_secret not in (work / ".env").read_text()
    names = [row["profile"] for row in setup.profiles_overview()["profiles"]]
    assert names[:1] == ["default"] and "work" in names
    # Applying again changes nothing on disk.
    again = setup.enable_for_profile("work")
    assert not any("link" in step for step in again["plan"])


def test_enable_profile_replaces_an_old_copy_with_a_link(home):
    work = home / "profiles" / "work"
    copy = work / "plugins" / "hermes-android"
    copy.mkdir(parents=True)
    (work / "config.yaml").write_text("model: {}\n")
    (copy / "plugin.yaml").write_text("name: hermes-android\nversion: 0.5.0\n")
    plan = setup.enable_for_profile("work")
    assert any("separate copy (version 0.5.0)" in step for step in plan["plan"])
    setup.enable_for_profile("work", apply=True)
    assert copy.is_symlink()
    backups = list(work.glob("plugins-backup-hermes-android-0.5.0-*"))
    assert len(backups) == 1 and (backups[0] / "plugin.yaml").exists()


def test_enable_profile_leaves_foreign_dirs_alone(home):
    work = home / "profiles" / "work"
    (work / "plugins" / "hermes-android").mkdir(parents=True)
    (work / "config.yaml").write_text("model: {}\n")
    result = setup.enable_for_profile("work", apply=True)
    assert "error" in result and not (work / "plugins" / "hermes-android").is_symlink()


def test_the_host_answers_pairing_for_other_profiles(home, monkeypatch):
    work = home / "profiles" / "work"
    work.mkdir(parents=True)
    (work / "config.yaml").write_text("model: {}\n")
    setup.configure()
    setup.install_credentials_json(KEY)
    # Not enabled there yet: the host says so and names the key the profile would share.
    reply = setup.pairing_for("work")
    assert reply["plugin_enabled"] is False and reply["host_profile"] == "default" and "secret" not in reply
    assert reply["server_key"]["state"] == "ok" and reply["server_key"]["shared"] is True
    monkeypatch.setattr(setup, "activate_profile", lambda name: {"gateway": "profile_restarted"})
    enabled = json.loads(tools.enable_command("work"))
    assert enabled["ok"] and enabled["restart_required"] is False
    monkeypatch.setattr(setup, "_api_server", lambda: {"enabled": True, "host": "192.168.1.5", "port": 8642,
                                                       "reachable_from_phone": True})
    reply = setup.pairing_for("work")
    work_secret = (work / ".env").read_text().split("HERMES_ANDROID_RPC_SECRET=")[1].splitlines()[0]
    assert reply["profile"] == "work" and reply["secret"] == work_secret
    assert setup.pairing_for("")["profile"] == "default"


def test_secondary_profiles_use_the_multiplexed_api_server(home):
    work = home / "profiles" / "work"
    work.mkdir(parents=True)
    (work / "config.yaml").write_text("model: {}\n")
    (home / ".env").write_text("API_SERVER_ENABLED=true\nAPI_SERVER_HOST=192.168.1.5\nAPI_SERVER_PORT=8650\n")
    _set("gateway.multiplex_profiles", "true", home)
    with setup.profile_scope("work"):
        api = setup._api_server()
    assert api["enabled"] and api["reachable_from_phone"] and api["port"] == 8650 and api["shared"]


def test_enable_command_needs_a_profile(home):
    assert json.loads(tools.enable_command(""))["ok"] is False
    assert json.loads(tools.enable_command("ghost"))["ok"] is False


def test_unknown_profile_is_refused(home):
    with pytest.raises(ValueError):
        setup.enable_for_profile("ghost")


def _pending(device):
    return DeviceStore().pending(device["device_id"], device["device_secret"])


def test_guardian_prechecks_and_duplicates_do_not_notify(home, pushed):
    device = _device()
    # Smart approvals: the hook fires before the guardian decides, and it usually decides alone.
    hooks.pre_approval_request(session_key="k", surface="smart", command="rm -rf build", tool_call_id="c1")
    hooks.post_approval_response(session_key="k", surface="smart", command="rm -rf build", tool_call_id="c1", choice="smart_approve")
    # A follower waiting on an identical pending prompt.
    hooks.pre_approval_request(session_key="k", surface="gateway", coalesced=True, command="rm -rf build", tool_call_id="c2")
    assert _pending(device) == [] and pushed == []


def test_real_prompt_notifies_once_with_its_chat(home, pushed, monkeypatch):
    device = _device()
    monkeypatch.setattr(hooks, "_session_platform", lambda sid: "desktop")
    for _ in range(2):  # Hermes may re-fire for the same tool call
        hooks.pre_approval_request(session_key="k", surface="gateway", session_id="s1", tool_call_id="c1",
                                   command="rm -rf build", description="recursive **delete**")
    [event] = _pending(device)
    assert event["event_type"] == "approval_required" and event["session_id"] == "s1"
    assert event["title"] == "Plan the trip" and event["body"].endswith(": recursive delete")
    assert pushed == [event["event_id"]]


def test_messaging_approvals_stay_in_their_channel(home, pushed, monkeypatch):
    device = _device()
    monkeypatch.setattr(hooks, "_session_platform", lambda sid: "telegram")
    hooks.pre_approval_request(session_key="k", surface="gateway", session_id="s1", tool_call_id="c1")
    assert _pending(device) == []


def test_an_answered_approval_is_withdrawn(home, pushed, monkeypatch):
    device = _device()
    monkeypatch.setattr(hooks, "_session_platform", lambda sid: "desktop")
    hooks.pre_approval_request(session_key="k", surface="gateway", session_id="s1", tool_call_id="c1")
    # Answered before the push went out: it just disappears.
    hooks.post_approval_response(session_key="k", surface="gateway", tool_call_id="c1", choice="once")
    assert _pending(device) == []

    hooks.pre_approval_request(session_key="k", surface="gateway", session_id="s1", tool_call_id="c2")
    [notice] = _pending(device)
    store = DeviceStore()
    assert store.begin_push(notice["event_id"]) is not None
    store.finish_push(notice["event_id"], "success")
    # Already on the phone: a resolution event tells the app to remove it.
    hooks.post_approval_response(session_key="k", surface="gateway", tool_call_id="c2", choice="deny")
    [resolved] = _pending(device)
    assert resolved["event_type"] == "approval_resolved" and resolved["source_id"] == notice["event_id"]
