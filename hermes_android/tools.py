"""Agent tools and slash commands for guided Android notification setup.

Tools return JSON and never include the pairing secret or key material. ``/android-pair`` is the
one exception: the app calls it over its authenticated chat connection (``command.dispatch``,
which never enters the model's history) to pair without the user copying a secret. It refuses
to answer inside messaging channels such as Telegram, where the reply would be posted to a chat.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import setup

TOOLSET = "hermes-android"


def _schema(name: str, description: str, properties: dict | None = None, required: tuple = ()) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": list(required)}}


def _wrap(fn: Callable[[dict], Any]) -> Callable[..., str]:
    def handler(args: dict, **_kw) -> str:
        try:
            return json.dumps({"ok": True, **fn(args or {})}, ensure_ascii=False, default=str)
        except Exception as exc:  # report, never raise into the agent loop
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return handler


TOOLS = (
    (_schema("hermes_android_status",
             "Diagnose Android push notifications for this Hermes profile: API server, pairing secret, "
             "Firebase service-account key, paired devices and scheduled jobs that do not notify the phone yet. "
             "Returns next_steps. Start here, and after every change."),
     _wrap(lambda a: setup.status()), "📱"),
    (_schema("hermes_android_configure",
             "Enable the hermes_android platform for this profile and create its pairing secret if missing. "
             "Idempotent; never returns the secret. A gateway restart is required afterwards."),
     _wrap(lambda a: setup.configure()), "🔧"),
    (_schema("hermes_android_install_credentials",
             "Install the user's Firebase service-account key (JSON) for this profile: validates it, stores it "
             "owner-only under the profile, points the config at it and deletes the source copy. Only for a key the "
             "user already placed on the server (for example with scp). Never ask for the key as a chat attachment: "
             "attachments are expanded into the prompt. Do NOT read, print or summarize the file yourself.",
             {"path": {"type": "string", "description": "Path of the service-account JSON on the server"},
              "delete_source": {"type": "boolean", "description": "Delete the uploaded copy after installing (default true)"}},
             ("path",)),
     _wrap(lambda a: setup.install_credentials(a.get("path", ""), bool(a.get("delete_source", True)))), "🔑"),
    (_schema("hermes_android_route_crons",
             "Add the paired phone (hermes_android:home) next to the existing destinations of scheduled jobs, the "
             "way Telegram receives them. Call with apply=false to list, then apply=true only after the user agrees. "
             "Jobs delivering only to local are left alone.",
             {"apply": {"type": "boolean", "description": "false = list only (default); true = update the jobs"},
              "profile": {"type": "string", "description": "Another profile's jobs (default: this profile)"}}),
     _wrap(lambda a: setup.route_crons(bool(a.get("apply", False)), str(a.get("profile") or ""))), "⏰"),
    (_schema("hermes_android_profiles",
             "List every Hermes profile and whether the phone can be used with it: plugin installed and enabled, "
             "pairing secret, Firebase key, paired devices. Use it when the user asks which profiles use the app."),
     _wrap(lambda a: setup.profiles_overview()), "👥"),
    (_schema("hermes_android_enable_profile",
             "Let another profile use the Android app: copies this plugin there, enables it, creates its pairing secret, "
             "configures the platform and reuses this profile's Firebase key. Call with apply=false to show the plan, "
             "then apply=true only after the user confirms. A gateway restart is needed afterwards.",
             {"profile": {"type": "string", "description": "Profile name, as listed by hermes_android_profiles"},
              "apply": {"type": "boolean", "description": "false = show the plan (default); true = do it"}},
             ("profile",)),
     _wrap(lambda a: setup.enable_for_profile(str(a.get("profile", "")), bool(a.get("apply", False)))), "➕"),
    (_schema("hermes_android_send_test",
             "Send a test notification to every phone paired with this profile and report FCM's answer."),
     _wrap(lambda a: setup.send_test()), "🔔"),
)


def _is_messaging_surface() -> bool:
    try:
        from gateway.session_context import session_is_messaging_surface
        return session_is_messaging_surface()
    except Exception:
        return False


def pair_command(_raw: str = "") -> str:
    if _is_messaging_surface():
        return "Pairing is done from the Hermes Mobile app (Notifications → Pair with this server)."
    return json.dumps(setup.pairing_payload(), ensure_ascii=False)


def credentials_command(raw: str = "") -> str:
    """App upload of the Firebase service-account key (base64). Never echoes key material."""
    if _is_messaging_surface():
        return json.dumps({"ok": False, "error": "Upload the key from the Hermes Mobile app."})
    try:
        return json.dumps({"ok": True, **setup.install_credentials_upload(raw)})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def test_command(_raw: str = "") -> str:
    try:
        return json.dumps({"ok": True, **setup.send_test()}, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def status_command(_raw: str = "") -> str:
    report = setup.status()
    lines = [f"Hermes Android {report['plugin_version']} · profile {report['profile']}",
             f"Platform: {'on' if report['platform_enabled'] else 'off'} · pairing secret: {report['pairing_secret']}",
             f"API server: {'on' if report['api_server']['enabled'] else 'off'} "
             f"({report['api_server']['host']}:{report['api_server']['port']})",
             f"Firebase key: {report['firebase_service_account']['state']}",
             f"Devices: {report['devices']}",
             "", "Next:"] + [f"- {step}" for step in report["next_steps"]]
    return "\n".join(lines)


def register(ctx) -> None:
    if hasattr(ctx, "register_tool"):
        for schema, handler, emoji in TOOLS:
            ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler,
                              description=schema["description"], emoji=emoji)
    if hasattr(ctx, "register_command"):
        ctx.register_command("android-pair", pair_command,
                             description="Pairing data for the Hermes Mobile app (used by the app itself)")
        ctx.register_command("android-credentials", credentials_command,
                             description="Install the Firebase service-account key (used by the app's upload button)")
        ctx.register_command("android-test", test_command, description="Send a test notification to paired phones")
        ctx.register_command("android-status", status_command,
                             description="Android notifications: setup status and next steps")
    if hasattr(ctx, "register_skill"):
        from pathlib import Path
        skill = Path(__file__).resolve().parent.parent / "skills" / "setup" / "SKILL.md"
        if skill.exists():
            ctx.register_skill("setup", skill, description="Set up Android push notifications (Firebase + pairing)")
