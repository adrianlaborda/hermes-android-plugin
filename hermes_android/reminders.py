"""Route conversational reminders through upstream's real cron delivery fanout.

No scheduler patch, extra timer, ledger polling or output/transcript scraping.
This seam covers the cronjob tool, not direct dashboard CRUD or existing jobs.
"""
from .store import DeviceStore

MOBILE_TARGET = "hermes_android:home"
# Hermes 0.22 renamed the tool to cronjob_manage (and resolves the old name to it); older releases call it cronjob.
CRON_TOOLS = frozenset({"cronjob", "cronjob_manage"})


def mobile_reminders_enabled() -> bool:
    from gateway.config import Platform, load_gateway_config
    config = load_gateway_config().platforms.get(Platform("hermes_android"))
    if not config or not config.enabled or (config.extra or {}).get("mirror_reminders") is False:
        return False
    with DeviceStore()._transaction() as conn:
        return conn.execute("SELECT 1 FROM devices WHERE state='active' LIMIT 1").fetchone() is not None


def primary_channel_enabled() -> bool:
    """platforms.hermes_android.primary_channel: the phone is the primary channel for reminders made outside a
    messaging channel (default on). Read like hooks._turn_mode: a bare `off` is YAML false, and the string forms
    `false`, `off`, `no` and `0` count too. A missing key or an unreadable config keeps the default."""
    try:
        from hermes_cli.config import load_config
        section = ((load_config() or {}).get("platforms") or {}).get("hermes_android") or {}
        raw = section.get("primary_channel")
    except Exception:
        return True
    if raw is None:
        return True
    if raw is False:
        return False
    return str(raw).strip().lower() not in {"false", "off", "no", "0"}


def with_mobile_target(value, drop_origin: bool = False):
    from tools.cronjob_job_args import _normalize_deliver_param
    delivery = _normalize_deliver_param(value) or "origin"
    parts = [p.strip() for p in delivery.split(",") if p.strip()]
    # Explicit local-only is an opt-out. Keep selective mobile destinations and
    # broadcast semantics; do not widen a specific device to every paired device.
    if any(p.lower() in {"local", "all", "hermes_android"}
           or p.lower().startswith("hermes_android:") for p in parts):
        return value
    if drop_origin:
        # Outside a messaging channel "origin" has no chat of its own: upstream would resolve it to the first
        # messaging home channel (Telegram…). The phone is the place the reminder belongs.
        parts = [p for p in parts if p.lower() != "origin"]
    return ",".join([*parts, MOBILE_TARGET])


def _from_app(platform=None) -> bool:
    """Whether the reminder is asked in a Hermes Mobile chat. Middleware gets no platform kwarg today: the
    session's source (set per turn by the gateway) says it."""
    from .tools import APP_SURFACES
    source = platform
    if not source:
        try:
            from gateway.session_context import get_session_env
            source = get_session_env("HERMES_SESSION_SOURCE", "")
        except Exception:
            source = ""
    return str(source or "").strip().lower() in APP_SURFACES


def route_reminder(*, tool_name=None, args=None, platform=None, **kwargs):
    if tool_name not in CRON_TOOLS or not isinstance(args, dict):
        return None
    action = args.get("action")
    if action not in {"create", "update"}:
        return None
    if action == "update" and not any(args.get(k) is not None for k in ("deliver", "failure_deliver")):
        return None  # Do not reset a stored destination during a schedule/prompt edit.
    if not mobile_reminders_enabled():
        return None
    # App chats always drop origin. Desktop, TUI, CLI and API reminders drop it too while the phone is the
    # primary channel; inside a messaging channel origin is that real chat and stays.
    from . import tools
    drop_origin = _from_app(platform) or (primary_channel_enabled() and not tools._is_messaging_surface())
    updated = dict(args)
    if action == "create" or args.get("deliver") is not None:
        updated["deliver"] = with_mobile_target(args.get("deliver"), drop_origin)
    if args.get("failure_deliver") is not None:
        updated["failure_deliver"] = with_mobile_target(args["failure_deliver"], drop_origin)
    if updated == args:
        return None
    return {"args": updated, "source": "hermes-android",
            "reason": "Also deliver this reminder to the profile's paired mobile devices"}
