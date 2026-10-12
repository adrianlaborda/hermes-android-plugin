"""Route conversational reminders through upstream's real cron delivery fanout.

No scheduler patch, extra timer, ledger polling or output/transcript scraping.
This seam covers the cronjob tool, not direct dashboard CRUD or existing jobs.
"""
from .store import DeviceStore

MOBILE_TARGET = "hermes_android:home"


def mobile_reminders_enabled() -> bool:
    from gateway.config import Platform, load_gateway_config
    config = load_gateway_config().platforms.get(Platform("hermes_android"))
    if not config or not config.enabled or (config.extra or {}).get("mirror_reminders") is False:
        return False
    with DeviceStore()._transaction() as conn:
        return conn.execute("SELECT 1 FROM devices WHERE state='active' LIMIT 1").fetchone() is not None


def with_mobile_target(value):
    from tools.cronjob_job_args import _normalize_deliver_param
    delivery = _normalize_deliver_param(value) or "origin"
    parts = [p.strip() for p in delivery.split(",") if p.strip()]
    # Explicit local-only is an opt-out. Keep selective mobile destinations and
    # broadcast semantics; do not widen a specific device to every paired device.
    if any(p.lower() in {"local", "all", "hermes_android"}
           or p.lower().startswith("hermes_android:") for p in parts):
        return value
    return ",".join([*parts, MOBILE_TARGET])


def route_reminder(*, tool_name=None, args=None, **kwargs):
    if tool_name != "cronjob" or not isinstance(args, dict):
        return None
    action = args.get("action")
    if action not in {"create", "update"}:
        return None
    if action == "update" and not any(args.get(k) is not None for k in ("deliver", "failure_deliver")):
        return None  # Do not reset a stored destination during a schedule/prompt edit.
    if not mobile_reminders_enabled():
        return None
    updated = dict(args)
    if action == "create" or args.get("deliver") is not None:
        updated["deliver"] = with_mobile_target(args.get("deliver"))
    if args.get("failure_deliver") is not None:
        updated["failure_deliver"] = with_mobile_target(args["failure_deliver"])
    if updated == args:
        return None
    return {"args": updated, "source": "hermes-android",
            "reason": "Also deliver this reminder to the profile's paired mobile devices"}
