"""Guided setup: everything an agent needs to configure Android notifications for one profile.

Every function here works on the *current* profile (the HERMES_HOME bound to the session that
calls it), never prints or returns a secret except :func:`pairing_payload`, which only the
app-facing slash command exposes, and only outside messaging channels.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

PLATFORM_NAME = "hermes_android"
HOME_TARGET = f"{PLATFORM_NAME}:home"
SECRET_ENV = "HERMES_ANDROID_RPC_SECRET"
MIN_SECRET_LENGTH = 32
DEFAULT_API_SERVER_PORT = 8642
CREDENTIALS_FILE = "fcm-service-account.json"
PLUGIN_VERSION = "0.5.0"
MAX_KEY_BYTES = 64 * 1024


# ── environment helpers ──────────────────────────────────────────────────────

def _home() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home())


def profile_name() -> str:
    try:
        from hermes_constants import profile_name_for_home
        name = profile_name_for_home(_home())
        if name:
            return str(name)
    except Exception:
        pass
    try:
        from hermes_cli.profiles import get_active_profile_name
        return get_active_profile_name() or "default"
    except Exception:
        return "default"


def _is_launch_home() -> bool:
    """Whether the active profile is the one this process started with: only then does os.environ
    (filled from that profile's .env at start-up) describe it."""
    launch = os.environ.get("HERMES_HOME", "").strip()
    try:
        from hermes_constants import get_default_hermes_root
        launch_path = Path(os.path.expanduser(launch)) if launch else get_default_hermes_root()
        return launch_path.resolve() == _home().resolve()
    except Exception:
        return True


def _dotenv(name: str) -> str:
    try:
        from hermes_cli.config import invalidate_env_cache, load_env
        invalidate_env_cache()
        return str(load_env().get(name) or "").strip()
    except Exception:
        return ""


def _env(name: str) -> str:
    """The active profile's value: its .env first; the process environment only for the launch profile."""
    value = _dotenv(name)
    if value or not _is_launch_home():
        return value
    return str(os.getenv(name) or "").strip()


def _secret() -> str:
    # The profile's .env wins: configure() writes it there and this process's environment does not see
    # the new value until a restart. For another profile, the inherited environment must never count.
    value = _dotenv(SECRET_ENV)
    if value or not _is_launch_home():
        return value
    from gateway.platforms._shared import get_scoped_secret
    return str(get_scoped_secret(SECRET_ENV, "") or "")


def _platform_config():
    from gateway.config import Platform, load_gateway_config
    return load_gateway_config().platforms.get(Platform(PLATFORM_NAME))


def _api_server() -> dict[str, Any]:
    """Whether the official API server (which carries the plugin's HTTP route) is on, and where."""
    try:
        from gateway.config import Platform, load_gateway_config
        cfg = load_gateway_config().platforms.get(Platform.API_SERVER)
    except Exception:
        cfg = None
    extra = dict(getattr(cfg, "extra", None) or {})
    host = str(extra.get("host") or _env("API_SERVER_HOST") or "127.0.0.1")
    try:
        port = int(extra.get("port") or _env("API_SERVER_PORT") or DEFAULT_API_SERVER_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_API_SERVER_PORT
    # The gateway turns API_SERVER_* from .env into this platform; a process that has not loaded
    # .env (or loaded it before an edit) would otherwise report a running server as off.
    enabled = bool(cfg and cfg.enabled) or _env("API_SERVER_ENABLED").lower() in {"1", "true", "yes", "on"}
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    return {"enabled": enabled, "host": host, "port": port,
            "reachable_from_phone": enabled and not loopback}


def _credentials_path() -> str:
    cfg = _platform_config()
    path = str(((getattr(cfg, "extra", None) or {}).get("credentials_path")) or "").strip()
    if path:
        return path
    from gateway.platforms._shared import get_scoped_secret
    return str(get_scoped_secret("GOOGLE_APPLICATION_CREDENTIALS", "") or "")


def validate_service_account(raw: Any) -> dict[str, str]:
    """Return {project_id, client_email} of a Firebase service-account key, or raise ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("The file is not a JSON object.")
    if raw.get("type") != "service_account":
        if "project_info" in raw and "client" in raw:
            raise ValueError("This is google-services.json (the Android app config). Import it in the app; "
                             "the server needs the service-account key instead.")
        raise ValueError("Not a service-account key (type must be service_account).")
    for field in ("project_id", "client_email", "private_key"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise ValueError(f"The key is missing {field}.")
    if "BEGIN PRIVATE KEY" not in raw["private_key"]:
        raise ValueError("The private_key field is not a PEM private key.")
    return {"project_id": raw["project_id"], "client_email": raw["client_email"]}


def _credentials_state() -> dict[str, Any]:
    path = _credentials_path()
    if not path:
        return {"state": "missing"}
    try:
        with open(path, encoding="utf-8") as handle:
            info = validate_service_account(json.load(handle))
    except FileNotFoundError:
        return {"state": "missing_file", "path": path}
    except PermissionError:
        return {"state": "unreadable", "path": path}
    except (ValueError, json.JSONDecodeError) as exc:
        return {"state": "invalid", "path": path, "reason": str(exc)}
    domain = info["client_email"].split("@")[-1]
    return {"state": "ok", "path": path, "project_id": info["project_id"], "account_domain": domain}


def _devices() -> dict[str, int]:
    from .store import DeviceStore
    with DeviceStore()._transaction() as conn:
        rows = conn.execute("SELECT state, COUNT(*) FROM devices GROUP BY state").fetchall()
    return {str(state): int(count) for state, count in rows}


def _cron_plan() -> list[dict[str, Any]]:
    """Jobs that deliver somewhere other than local and do not include the phone yet."""
    from cron.jobs import list_jobs
    from .reminders import with_mobile_target
    plan = []
    for job in list_jobs(include_disabled=False):
        deliver = job.get("deliver")
        target = with_mobile_target(deliver)
        if target != deliver:
            plan.append({"id": job.get("id"), "name": job.get("name") or job.get("id"),
                         "deliver": deliver, "new_deliver": target})
    return plan


# ── public operations (tools / commands) ─────────────────────────────────────

def status() -> dict[str, Any]:
    cfg = _platform_config()
    secret = _secret()
    api = _api_server()
    creds = _credentials_state()
    try:
        devices = _devices()
    except Exception as exc:  # store unavailable must not hide the rest of the diagnosis
        devices = {"error": str(exc)}
    try:
        crons = _cron_plan()
    except Exception as exc:
        crons = [{"error": str(exc)}]
    secret_state = "missing" if not secret else ("too_short" if len(secret) < MIN_SECRET_LENGTH else "ok")
    steps = []
    if not api["enabled"]:
        steps.append("Enable the official API server (API_SERVER_ENABLED=true, a strong API_SERVER_KEY, "
                     "API_SERVER_HOST set to a LAN/VPN address). Ask the user first: it exposes the agent on the network.")
    elif not api["reachable_from_phone"]:
        steps.append("API_SERVER_HOST is loopback; the phone cannot reach it. Bind it to a LAN/VPN address the phone uses.")
    if not (cfg and cfg.enabled) or secret_state != "ok":
        steps.append("Run hermes_android_configure.")
    if creds["state"] != "ok":
        steps.append("Install the Firebase service-account key: in the app, Notifications → Upload server key "
                     "(or, if the user copied it to the server, hermes_android_install_credentials). Never via chat attachment.")
    if not devices.get("active"):
        steps.append("In the app: Notifications → import google-services.json → Pair with this server.")
    if any("new_deliver" in job for job in crons):
        steps.append("Offer hermes_android_route_crons to add the phone to existing scheduled jobs.")
    return {
        "plugin_version": PLUGIN_VERSION, "profile": profile_name(),
        "platform_enabled": bool(cfg and cfg.enabled), "pairing_secret": secret_state,
        "api_server": api, "firebase_service_account": creds, "devices": devices,
        "cron_jobs_without_phone": crons,
        "note": "Platform and secret changes need a gateway restart (`hermes gateway restart`).",
        "next_steps": steps or ["Everything is configured. Send a test with hermes_android_send_test."],
    }


def configure() -> dict[str, Any]:
    """Enable the platform and create the pairing secret if needed. Never returns the secret."""
    from hermes_cli.config import save_env_value, set_config_value as _set
    def set_config_value(key: str, value: str) -> None:
        with contextlib.redirect_stdout(io.StringIO()):  # CLI helpers print "✓ Set …"
            _set(key, value)
    changed = []
    secret = _secret()
    if len(secret) < MIN_SECRET_LENGTH:
        with contextlib.redirect_stdout(io.StringIO()):
            save_env_value(SECRET_ENV, secrets.token_urlsafe(32))
        changed.append("pairing secret created")
    cfg = _platform_config()
    home = getattr(cfg, "home_channel", None) if cfg else None
    if not (cfg and cfg.enabled):
        set_config_value(f"platforms.{PLATFORM_NAME}.enabled", "true")
        changed.append("platform enabled")
    if not (home and getattr(home, "chat_id", "")):
        set_config_value(f"platforms.{PLATFORM_NAME}.home_channel.platform", PLATFORM_NAME)
        set_config_value(f"platforms.{PLATFORM_NAME}.home_channel.chat_id", "home")
        set_config_value(f"platforms.{PLATFORM_NAME}.home_channel.name", "Android")
        changed.append("home channel set")
    return {"changed": changed, "restart_required": bool(changed), "profile": profile_name(),
            "next": "Restart the gateway (`hermes gateway restart`) so the platform loads, then check hermes_android_status."}


def install_credentials_json(raw: Any) -> dict[str, Any]:
    """Validate a service-account key, store it owner-only in this profile and point the config at it."""
    from hermes_cli.config import set_config_value as _set
    def set_config_value(key: str, value: str) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            _set(key, value)
    info = validate_service_account(raw)
    target_dir = _home() / "credentials" / "hermes-android"
    target_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(target_dir, stat.S_IRWXU)
    target = target_dir / CREDENTIALS_FILE
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    os.replace(tmp, target)
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    set_config_value(f"platforms.{PLATFORM_NAME}.credentials_path", str(target))
    set_config_value(f"platforms.{PLATFORM_NAME}.project_id", info["project_id"])
    # The adapter resolves the key on every send, so no restart is needed for a new/rotated key.
    return {"installed": str(target), "project_id": info["project_id"]}


def install_credentials(path: str, delete_source: bool = True) -> dict[str, Any]:
    """Install a key file already on the server (copied there by the user, e.g. with scp)."""
    source = Path(os.path.expanduser(str(path or ""))).resolve()
    if not source.is_file():
        raise ValueError(f"No file at {source}.")
    if source.stat().st_size > MAX_KEY_BYTES:
        raise ValueError("The file is too large to be a service-account key.")
    with source.open(encoding="utf-8") as handle:
        result = install_credentials_json(json.load(handle))
    removed = False
    if delete_source and str(source) != result["installed"]:
        with contextlib.suppress(OSError):
            source.unlink()
            removed = True
    return {**result, "source_deleted": removed}


def install_credentials_upload(encoded: str) -> dict[str, Any]:
    """The app's upload path: base64 of the key file, sent through the authenticated chat connection."""
    import base64
    data = base64.b64decode(str(encoded or "").strip(), validate=True)
    if len(data) > MAX_KEY_BYTES:
        raise ValueError("The file is too large to be a service-account key.")
    return install_credentials_json(json.loads(data.decode("utf-8")))


def route_crons(apply: bool = False, profile: str = "") -> dict[str, Any]:
    if profile and profile != profile_name():
        with profile_scope(profile):
            return {**route_crons(apply), "profile": profile}
    from cron.jobs import update_job
    plan = _cron_plan()
    if not apply:
        return {"dry_run": True, "jobs": plan}
    done = []
    for job in plan:
        update_job(job["id"], {"deliver": job["new_deliver"]})
        done.append(job["name"])
    return {"dry_run": False, "updated": done}


def _transport():
    from .fcm import FcmTransport
    cfg = _platform_config()
    return FcmTransport(_credentials_path(), str(((getattr(cfg, "extra", None) or {}).get("project_id")) or ""))


def deliver_events_now(event_ids: list[str]) -> dict[str, str]:
    """Push already-stored events from any process (hooks run where the turn ran, not in the gateway)."""
    from .adapter import deliver_event
    from .store import DeviceStore

    async def run() -> dict[str, str]:
        store, transport = DeviceStore(), _transport()
        return {event_id: await deliver_event(store, transport, event_id) for event_id in event_ids}

    return asyncio.run(run())


async def _send_test_async() -> dict[str, Any]:
    from .adapter import deliver_event
    from .store import DeviceStore
    store = DeviceStore()
    with store._transaction() as conn:
        devices = [row[0] for row in conn.execute("SELECT device_id FROM devices WHERE state='active'")]
    if not devices:
        return {"sent": 0, "error": "No paired device in this profile."}
    transport = _transport()
    outcomes = {}
    for device_id in devices:
        event = store.create_event(device_id=device_id, event_type="test", title="Hermes",
                                   body="Notifications work. This is a test from your Hermes server.",
                                   source="hermes-android")
        outcomes[device_id[:8]] = await deliver_event(store, transport, event["event_id"])
    return {"sent": len(devices), "outcomes": outcomes,
            "hint": "success = accepted by FCM; auth = service-account/project problem; permanent = stale device token."}


def send_test() -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_send_test_async())
    # Called from inside an event loop (async tool dispatch): run on a private loop in a worker thread.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _send_test_async()).result(timeout=120)


def pairing_payload() -> dict[str, Any]:
    """What the app needs to register itself: only for the authenticated app, never messaging chats."""
    secret = _secret()
    api = _api_server()
    ready = bool(api["enabled"] and len(secret) >= MIN_SECRET_LENGTH)
    key = _credentials_state()
    payload: dict[str, Any] = {"hermes_android_pairing": 1, "profile": profile_name(),
                               "plugin_version": PLUGIN_VERSION, "ready": ready,
                               "server_key": {"state": key["state"], "project_id": key.get("project_id", "")},
                               "api_server": {"host": api["host"], "port": api["port"],
                                              "reachable_from_phone": api["reachable_from_phone"]}}
    if ready:
        payload["secret"] = secret
    else:
        payload["problem"] = "api_server_disabled" if not api["enabled"] else "pairing_secret_missing"
    return payload


# ── other profiles ───────────────────────────────────────────────────────────

PLUGIN_NAME = "hermes-android"


@contextlib.contextmanager
def profile_scope(name: str):
    """Run the block as profile ``name`` (its HERMES_HOME: config, .env, cron, devices)."""
    from hermes_cli.profiles import get_profile_dir, profile_exists
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    if not profile_exists(name):
        raise ValueError(f"Unknown profile: {name}")
    token = set_hermes_home_override(str(get_profile_dir(name)))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def _plugin_enabled_in_config() -> bool:
    from hermes_cli.config import load_config
    plugins = (load_config() or {}).get("plugins") or {}
    return PLUGIN_NAME in (plugins.get("enabled") or []) and PLUGIN_NAME not in (plugins.get("disabled") or [])


def _profile_row(name: str) -> dict[str, Any]:
    with profile_scope(name):
        installed = (_home() / "plugins" / PLUGIN_NAME / "plugin.yaml").exists()
        row: dict[str, Any] = {"profile": name, "plugin_installed": installed,
                               "plugin_enabled": _plugin_enabled_in_config()}
        if installed:
            cfg = _platform_config()
            row["platform_enabled"] = bool(cfg and cfg.enabled)
            row["pairing_secret"] = "ok" if len(_secret()) >= MIN_SECRET_LENGTH else "missing"
            row["server_key"] = _credentials_state()["state"]
            try:
                row["active_devices"] = _devices().get("active", 0)
            except Exception:
                row["active_devices"] = 0
        return row


def profiles_overview() -> dict[str, Any]:
    from hermes_cli.profiles import list_profile_names
    rows = []
    for name in list_profile_names():
        try:
            rows.append(_profile_row(name))
        except Exception as exc:
            rows.append({"profile": name, "error": str(exc)})
    return {"current_profile": profile_name(), "profiles": rows,
            "note": "Each profile pairs separately: in the app, pick the profile in Notifications and tap Pair."}


def enable_for_profile(name: str, apply: bool = False) -> dict[str, Any]:
    """Make ``name`` usable from the app: install this plugin there, enable it, create its secret,
    configure the platform and reuse this profile's Firebase service-account key (the phone has a
    single Firebase project, so every profile must send through the same one)."""
    from hermes_cli.config import load_config, save_config
    source_dir = Path(__file__).resolve().parent.parent
    key_state = _credentials_state()
    key_raw = None
    if key_state["state"] == "ok":
        with open(key_state["path"], encoding="utf-8") as handle:
            key_raw = json.load(handle)
    before = _profile_row(name)
    plan = []
    if not before["plugin_installed"]:
        plan.append(f"copy plugin {PLUGIN_VERSION} into the profile")
    if not before["plugin_enabled"]:
        plan.append("enable the plugin in the profile's config")
    plan.append("enable the hermes_android platform and create its pairing secret (if missing)")
    if key_raw is not None and before.get("server_key") != "ok":
        plan.append(f"install the Firebase key of project {key_state['project_id']} (same as this profile)")
    elif key_raw is None and before.get("server_key") != "ok":
        plan.append("no Firebase key to reuse: upload one from the app for that profile")
    if not apply:
        return {"dry_run": True, "profile": name, "plan": plan, "current": before,
                "next": "Confirm with the user, then call again with apply=true. A gateway restart follows."}
    import shutil
    with profile_scope(name):
        target = _home() / "plugins" / PLUGIN_NAME
        if not (target / "plugin.yaml").exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        cfg = load_config() or {}
        plugins = cfg.setdefault("plugins", {})
        enabled = [p for p in (plugins.get("enabled") or []) if p != PLUGIN_NAME] + [PLUGIN_NAME]
        plugins["enabled"] = enabled
        plugins["disabled"] = [p for p in (plugins.get("disabled") or []) if p != PLUGIN_NAME]
        with contextlib.redirect_stdout(io.StringIO()):
            save_config(cfg, merge_existing=True)
        configured = configure()
        if key_raw is not None and _credentials_state()["state"] != "ok":
            install_credentials_json(key_raw)
    return {"dry_run": False, "profile": name, "done": plan, "configure": configured["changed"],
            "now": _profile_row(name), "restart_required": True,
            "next": ("Restart the gateway (`hermes gateway restart`). Then in the app: Notifications → "
                     f"select profile {name} → Pair with this server.")}

