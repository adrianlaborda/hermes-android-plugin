"""Turn-completion and approval notices through Hermes' real on_session_end / pre_approval_request /
post_approval_response hooks.

The notice is stored in the profile's device inbox (title = chat title, body = an excerpt of the answer)
and pushed right away from a background thread; the adapter's recovery loop retries anything that fails.
FCM still carries only the opaque event ID: the phone fetches title and body from the inbox.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
import re
import threading

from .store import DeviceStore

logger = logging.getLogger(__name__)
EXCERPT_CHARS = 600
TURN_MODES = {"all", "non_messaging", "never"}


def _active_devices(store: DeviceStore) -> list[str]:
    with store._transaction() as conn:
        return [r[0] for r in conn.execute("SELECT device_id FROM devices WHERE state='active'")]


def _turn_mode(key: str = "notify_turns") -> str:
    """platforms.hermes_android.notify_turns / notify_approvals: all | non_messaging (default) | never (false
    works too: YAML reads a bare `off` as false, and Hermes' config CLI turns `none` into null)."""
    try:
        from hermes_cli.config import load_config
        section = ((load_config() or {}).get("platforms") or {}).get("hermes_android") or {}
        raw = section.get(key)
        if raw is False:
            return "never"
        mode = str(raw or "non_messaging").strip().lower()
        return mode if mode in TURN_MODES else "non_messaging"
    except Exception:
        return "non_messaging"


def _is_messaging(platform) -> bool:
    """Telegram, Discord, WhatsApp…: that channel already told the user, so the phone stays quiet.
    Hermes Mobile's own chats (source "mobile") are not messaging: their answers are what the phone waits for."""
    from .tools import APP_SURFACES
    name = str(platform or "").strip().lower()
    try:
        from gateway.session_context import NON_MESSAGING_SESSION_SURFACES
        return bool(name) and name not in NON_MESSAGING_SESSION_SURFACES | APP_SURFACES | {"hermes_android"}
    except Exception:
        return name in {"telegram", "discord", "whatsapp", "slack", "signal", "matrix"}


def _plain(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)           # code blocks add nothing to a notice
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)              # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)           # links → their label
    text = re.sub(r"[*_`#>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _turn_summary(session_id: str) -> tuple[str, str]:
    """(chat title, excerpt of the last answer); empty strings when the session store has nothing yet."""
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        title = (db.get_session_title(session_id) or "").strip()
        messages = db.get_messages(session_id, limit=6, latest=True)
        answer = next((m.get("content") for m in reversed(messages)
                       if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip()), "")
        excerpt = _plain(answer)
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"
        return title, excerpt
    except Exception:
        logger.debug("hermes-android: no session summary for the notice", exc_info=True)
        return "", ""


def _push_soon(event_ids: list[str]) -> None:
    """Deliver now instead of waiting for the recovery loop (which may run in another process)."""
    if not event_ids:
        return

    def run() -> None:
        try:
            from .setup import deliver_events_now
            deliver_events_now(event_ids)
        except Exception:
            logger.warning("hermes-android: immediate push deferred to the recovery loop")

    # Threads do not inherit context variables: carry the session's profile (HERMES_HOME override) along.
    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(run,), name="hermes-android-push", daemon=True).start()


def on_session_end(*, session_id=None, turn_id=None, completed=False, failed=False,
                   interrupted=False, platform=None, **kwargs):
    if platform == "cron":
        return  # cron results arrive through the job's own delivery (hermes_android:home)
    if not session_id or not turn_id or interrupted or not (completed or failed):
        return
    mode = _turn_mode()
    if mode == "never" or (mode == "non_messaging" and _is_messaging(platform)):
        return
    store = DeviceStore()
    devices = _active_devices(store)
    if not devices:
        return
    title, excerpt = _turn_summary(str(session_id))
    if failed:
        body = "The task failed or needs your attention." + (f"\n\n{excerpt}" if excerpt else "")
    else:
        body = excerpt or "Your response is ready."
    created = []
    for device_id in devices:
        event = store.create_event(
            device_id=device_id, event_type="turn_failed" if failed else "turn_completed",
            title=title or "Hermes", body=body, source=str(platform or "hermes"), session_id=str(session_id),
            dedup_key=f"turn:{session_id}:{turn_id}",
        )
        if event.get("state") == "pending" and not event.get("deduplicated"):
            created.append(event["event_id"])
    _push_soon(created)


# Hermes fires pre_approval_request for its smart-approval guardian *before* the guardian decides; nearly
# always it approves or denies on its own, and when it escalates a real prompt follows with its own hook.
OBSERVER_ONLY_SURFACES = {"smart"}


def _session_platform(session_id) -> str | None:
    """Where the session lives (desktop, telegram, cli…), from Hermes' session store."""
    if not session_id:
        return None
    try:
        from hermes_state import SessionDB
        return ((SessionDB().get_session(str(session_id)) or {}).get("source")) or None
    except Exception:
        return None


def _approval_key(session_key, tool_call_id, command) -> str:
    """Pairs a request with its resolution: post_approval_response carries the same payload."""
    ident = tool_call_id or hashlib.sha256(str(command or "").encode()).hexdigest()[:16]
    return f"approval:{session_key or ''}:{ident}"


def _is_prompt(surface, coalesced) -> bool:
    """A real prompt someone has to answer: not the guardian's pre-check, not a duplicate of a pending one."""
    return str(surface or "") not in OBSERVER_ONLY_SURFACES and not coalesced


def pre_approval_request(*, session_key=None, surface=None, coalesced=False, session_id=None, description="",
                         tool_call_id=None, command="", **kwargs):
    if not _is_prompt(surface, coalesced):
        return
    mode = _turn_mode("notify_approvals")
    if mode == "never" or (mode == "non_messaging" and _is_messaging(_session_platform(session_id))):
        return  # Telegram & co. show the approval buttons themselves
    store = DeviceStore()
    devices = _active_devices(store)
    if not devices:
        return
    title = _turn_summary(str(session_id))[0] if session_id else ""
    detail = _plain(str(description or ""))[:200]
    body = "Hermes needs your approval to continue" + (f": {detail}" if detail else ".")
    key = _approval_key(session_key, tool_call_id, command)
    created = []
    for device_id in devices:
        # session_id lets the phone open that chat, where the pending approval is replayed.
        event = store.create_event(device_id=device_id, event_type="approval_required", title=title or "Hermes",
                                   body=body, priority="high", source=str(surface or "hermes"),
                                   session_id=str(session_id) if session_id else None, dedup_key=key)
        if event.get("state") == "pending" and not event.get("deduplicated"):
            created.append(event["event_id"])
    _push_soon(created)


def post_approval_response(*, session_key=None, surface=None, coalesced=False, tool_call_id=None, command="",
                           choice=None, **kwargs):
    """Answered anywhere (Desktop, Telegram, the app) or timed out: withdraw the phone's notice."""
    if not _is_prompt(surface, coalesced):
        return
    key = _approval_key(session_key, tool_call_id, command)
    store = DeviceStore()
    created = []
    for device_id in _active_devices(store):
        notice = store.withdraw(device_id, key)
        if notice is None or not notice.get("push_sent_at"):
            continue  # never reached the phone: withdrawing it is enough
        event = store.create_event(device_id=device_id, event_type="approval_resolved", title="Hermes",
                                   body="The approval was answered.", priority="low",
                                   source_id=notice["event_id"], session_id=notice.get("session_id"),
                                   dedup_key=f"{key}:resolved")
        if event.get("state") == "pending" and not event.get("deduplicated"):
            created.append(event["event_id"])
    _push_soon(created)
