# Hermes Android plugin

[![CI](https://github.com/adrianlaborda/hermes-android-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/adrianlaborda/hermes-android-plugin/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/adrianlaborda/hermes-android-plugin?sort=semver)](https://github.com/adrianlaborda/hermes-android-plugin/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)

Push notifications from your own [Hermes Agent](https://github.com/NousResearch/hermes-agent) to the
[Hermes Mobile](https://github.com/adrianlaborda/hermes-mobile) Android app: reminders, scheduled jobs, finished turns
and approval requests, delivered the way Telegram receives them. It is self-hosted end to end. You bring your own
Firebase project, the APK contains no keys, and there is no relay in the middle. It installs as a normal Hermes platform
plugin, with no fork or patch of Hermes core.

> **Unofficial.** This is a community project. It is not affiliated with or endorsed by Nous Research.

**Requirements:** Hermes Agent with platform HTTP callbacks (tested on v0.21.7) and Python 3.11 or later. Changes are
listed in [CHANGELOG.md](CHANGELOG.md).

## Quick start: let Hermes do it

Open a chat with Hermes, in Hermes Mobile or anywhere else, and say:

> Install the plugin from https://github.com/adrianlaborda/hermes-android-plugin and set up notifications for my Android phone.

Hermes installs the plugin and then follows its bundled `hermes-android:setup` skill. It runs a diagnosis, prepares the
server, walks you through the three Firebase console steps, and helps you pair the phone and send a test.

The only things you do yourself:

1. **In the Firebase console:** create or reuse a project, add an Android app with the package name shown in the app's
   **Notifications** screen, download `google-services.json`, and generate a service-account key.
2. **In Hermes Mobile → Notifications:**
   - **Import google-services.json**.
   - **Upload server key** (the service-account JSON).
   - **Pair with this server.**

The app sends the server key over its authenticated connection, never through the chat. Chat attachments are expanded
into the model's prompt, so never paste or attach the key there.

## Manual setup

### 1. Install

```sh
hermes plugins install adrianlaborda/hermes-android-plugin
hermes plugins enable hermes-android
hermes android-status          # or /android-status in any chat
```

Update it later with `hermes plugins update hermes-android`. State lives in `<HERMES_HOME>/plugin-data/hermes-android/`,
outside the replaceable plugin directory.

### 2. API server

The phone talks to the plugin through the official API server, which carries
`POST /p/<profile>/api/platforms/hermes_android/events`. In the profile's `.env`:

```dotenv
API_SERVER_ENABLED=true
API_SERVER_HOST=192.168.1.10        # a LAN/VPN address the phone can reach, not 0.0.0.0 on a public host
API_SERVER_PORT=8642
API_SERVER_KEY=<strong random secret>
```

The API server lets authorized clients run the agent, so keep it on your LAN or VPN and firewall the port. The app
accepts plain HTTP only for private and local addresses, exactly like its chat connection; anything public needs HTTPS
through a reverse proxy.

### 3. Platform and pairing secret

Run `/android-status`, then ask Hermes to call `hermes_android_configure`, or set it up by hand:

```dotenv
HERMES_ANDROID_RPC_SECRET=<random, at least 32 characters>   # python -c "import secrets;print(secrets.token_urlsafe(32))"
```

```yaml
platforms:
  hermes_android:
    enabled: true
    home_channel: {platform: hermes_android, chat_id: home, name: Android}
```

Restart the gateway: `hermes gateway restart`.

### 4. Firebase

In <https://console.firebase.google.com>:

1. **Create a project**, or reuse one. Google Analytics is optional.
2. Go to **Project settings → General → Your apps → Add app → Android**. Use the **exact package name** shown in Hermes
   Mobile under **Notifications**. Leave the nickname and SHA-1 empty. Then **Register app** and
   **Download google-services.json**, and skip the SDK steps.
3. Go to **Project settings → Service accounts → Generate new private key**. This downloads the server key (a secret).
4. *Firebase Cloud Messaging API (V1)* should show **Enabled** under **Project settings → Cloud Messaging**. It is on by
   default.

The service-account key goes to the server: use **Upload server key** in the app. Alternatively, `scp` it to the server
and ask Hermes to run `hermes_android_install_credentials` with its path. Either way, the plugin validates it, stores it
owner-only at `<HERMES_HOME>/credentials/hermes-android/fcm-service-account.json`, sets `credentials_path` and
`project_id`, and deletes the uploaded copy. A new or rotated key is picked up without a restart.

If the app later reports *"Firebase rejected this phone's registration"*, the project's Android API key is restricted
in a way that blocks the app, typically a *Websites* restriction. Go to Google Cloud Console → **APIs & Services →
Credentials → Android key (auto created by Firebase)**. Set **Application restrictions** to *None*, or to *Android apps*
with the app's package and signing SHA-1.

### 5. Phone

In Hermes Mobile, open the menu, then **Notifications** for the profile you configured:

1. **Import google-services.json**.
2. **Upload server key**, unless you already did step 4 on the server.
3. **Pair with this server.** The app fetches the API-server address and the pairing secret over its authenticated
   chat connection (`/android-pair`) and registers the phone. You never copy a secret. A manual URL and secret form
   remains available as a fallback.
4. **Send test.**

### 6. Scheduled jobs

New reminders created by talking to Hermes notify the phone automatically. To add the phone to jobs that already exist,
ask Hermes to run `hermes_android_route_crons`. It lists the affected jobs first and applies the change only after you
agree. Jobs created directly in the dashboard need `hermes_android:home` added to their delivery.

The phone is the primary channel by default. A reminder made outside a messaging channel (Desktop, the TUI or CLI, the
API, or the Hermes Mobile app) goes to the phone only, and Hermes does not fall back to a messaging home channel such as
Telegram. A reminder made inside Telegram still notifies its own chat, and the phone too. To turn this off, set
`platforms.hermes_android.primary_channel: false`, or in the app or a chat run
`/android-primary-channel [profile] [on|off]`. With no `on|off` the command reports the current setting. It replies
with JSON, `{"primary_channel": true|false, "profile": "<name>"}`, or `{"error": "..."}`. Changing the setting from a
messaging channel is refused.

### 7. More profiles

Hermes isolates profiles, so each one has to enable the plugin and pairs separately. You install the plugin
once. Ask Hermes, in a profile that already has it, *"enable Android notifications for the work profile"*. The app's
**Ask Hermes** button on a profile that is not enabled does exactly that. Hermes calls `hermes_android_enable_profile`,
which:

- links the plugin into that profile, so one install and one update serve every profile;
- creates that profile's own pairing secret;
- points it at the same Firebase key file.

The plugin goes live without a full gateway restart: it loads in the chat backend and only that profile restarts
inside the multiplexing gateway. In the app, the same is one tap: on a profile that is not enabled yet,
**Notifications → Enable for this profile** runs `/android-enable <profile>` and pairs the phone.

### What gets notified

| Event | Title / body | Default |
|---|---|---|
| Scheduled job or reminder delivered to `hermes_android:home` | the job's output | on |
| Finished or failed turn | chat title / excerpt of the answer | on for app, Desktop and API turns; off for Telegram-like channels, which already notify you |
| Approval request waiting for you | chat title / what the action does | on for app, Desktop and API sessions; off for Telegram-like channels, which show the buttons themselves |

`platforms.hermes_android.notify_turns` and `notify_approvals` (`all | non_messaging | never`) control turn and
approval notices. Hermes' smart-approval checks never notify: its guardian decides those on its own. When an approval is
answered anywhere or times out, its notice disappears from the phone.

Only an opaque event ID travels through FCM; the phone fetches the content from your server. Showing it on the lock
screen is a setting in the app.

## For agents

If you are an AI agent asked to set this up:

1. Install and enable the plugin with the commands in **Manual setup → 1**. Use your terminal tool if you have one;
   otherwise give the user the commands. Then **start a new session** so the plugin's tools load.
2. Load the `hermes-android:setup` skill and follow it. Start with `hermes_android_status`.
3. Tools (toolset `hermes-android`): `hermes_android_status`, `hermes_android_configure`,
   `hermes_android_install_credentials` (only for a key already on the server), `hermes_android_route_crons`
   (always `apply=false` first; optional `profile`), `hermes_android_profiles`, `hermes_android_enable_profile`
   (always `apply=false` first), `hermes_android_send_test`.
4. Rules:
   - Never request the service-account key as a chat attachment or paste.
   - Never print secrets or key files.
   - Ask before enabling the API server or restarting the gateway.
   - Each Hermes profile is configured and paired separately.

Slash commands: `/android-status` gives a human-readable status. `/android-pair`, `/android-credentials` and
`/android-test` are called by the app over `command.dispatch`, whose output never enters the model's history. The
first two refuse to answer in messaging channels such as Telegram. `/android-primary-channel [profile] [on|off]` reports
or sets the primary-channel option (see step 6); it never touches secrets.

## How it works

- **Extension points used:**
  - `ctx.register_platform`, and the adapter's `verify_http_event_request` / `dispatch_http_event`.
  - `on_session_end` (finished turns) and `pre_approval_request`.
  - `tool_request` middleware, which adds the phone to new `cronjob` requests (or `cronjob_manage`, on Hermes 0.22 and
    later).
  - `register_tool`, `register_command` and `register_skill` for the guided setup.
- **What travels through FCM:** an opaque event ID, the device ID and the protocol version, nothing else. The phone
  shows a private generic notice, then fetches the content from the inbox over the API server.
- **Protocol:** see [docs/protocol-v1.md](docs/protocol-v1.md).

> **Upgrading from `hermes-assistant` (≤ 0.2.1)?** 0.3.0 renamed everything to `hermes-android`: platform, cron target,
> endpoint and secret variable. Disable the old plugin, rename `platforms.hermes_assistant` and
> `HERMES_ASSISTANT_RPC_SECRET`, rewrite cron destinations and re-pair the phone.

## Limits

- **Scheduled jobs.** The plugin adds the phone to new `cronjob` requests (or `cronjob_manage`, on Hermes 0.22 and
  later) made through Hermes' normal tool pipeline, from any surface. Jobs that already exist, and jobs created directly
  in the dashboard or the scheduler API, are not changed. Route them with `hermes_android_route_crons`, or add
  `hermes_android:home` to their delivery. Explicit `local` delivery stays local. Set
  `platforms.hermes_android.mirror_reminders: false` to stop routing new jobs. Set
  `platforms.hermes_android.primary_channel: false` to keep `origin` for reminders made outside messaging channels
  (see [6. Scheduled jobs](#6-scheduled-jobs)).
- **Approvals.** Tapping an approval notice opens its chat, where the pending approval is replayed. Approvals from
  scheduled jobs have no chat to open.
- **Delivery.** Up to 3 push attempts, each with bounded HTTP retries. Undelivered events stay in the inbox for 7 days,
  and the phone picks them up when the app opens. Stable notification IDs and acknowledgements suppress duplicates.
- **Android.** Notifications depend on Google Play services, the app's permission and channel settings, and battery
  restrictions. A force-stopped app receives nothing until it is reopened.

## Development

```sh
pip install -e '.[test]'
HERMES_AGENT_SRC=/path/to/hermes-agent python -m pytest tests -q
```

Tests use synthetic devices and a local HTTP server, never real Firebase credentials. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). To report a vulnerability, see [SECURITY.md](SECURITY.md).
