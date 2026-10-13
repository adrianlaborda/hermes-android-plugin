# Hermes Android plugin

Push notifications from your own [Hermes Agent](https://github.com/NousResearch/hermes-agent) to the
**Hermes Mobile** Android app: reminders, scheduled jobs, finished turns and approval requests, delivered the way
Telegram receives them. It is self-hosted end to end. You bring your own Firebase project, the APK contains no keys,
and there is no relay in the middle. It installs as a normal Hermes platform plugin, with no fork or patch of Hermes core.

Version 0.5.0. It requires Hermes Agent with platform HTTP callbacks (validated on v0.21.5) and Python 3.11–3.13.

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

### 7. More profiles

Hermes isolates profiles, so each one has to enable the plugin and pairs separately. You install the plugin
once. Ask Hermes, in a profile that already has it, *"enable Android notifications for the work profile"*. The app's
**Ask Hermes** button on a profile that is not enabled does exactly that. Hermes calls `hermes_android_enable_profile`,
which:

- links the plugin into that profile, so one install and one update serve every profile;
- creates that profile's own pairing secret;
- points it at the same Firebase key file.

After a gateway restart, pick the profile in the app's **Notifications** screen and tap **Pair**.

### What gets notified

| Event | Title / body | Default |
|---|---|---|
| Scheduled job or reminder delivered to `hermes_android:home` | the job's output | on |
| Finished or failed turn | chat title / excerpt of the answer | on for app, Desktop and API turns; off for Telegram-like channels, which already notify you |
| Approval request | generic | on |

`platforms.hermes_android.notify_turns: all | non_messaging | never` controls turn notices.

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
first two refuse to answer in messaging channels such as Telegram.

## How it works

- **Extension points used:**
  - `ctx.register_platform`, and the adapter's `verify_http_event_request` / `dispatch_http_event`.
  - `on_session_end` (finished turns) and `pre_approval_request`.
  - `tool_request` middleware, which adds the phone to new `cronjob` requests.
  - `register_tool`, `register_command` and `register_skill` for the guided setup.
- **What travels through FCM:** an opaque event ID, the device ID and the protocol version, nothing else. The phone
  shows a private generic notice, then fetches the content from the inbox over the API server.
- **Protocol:** see [docs/protocol-v1.md](docs/protocol-v1.md).

> **Upgrading from `hermes-assistant` (≤ 0.2.1)?** 0.3.0 renamed everything to `hermes-android`: platform, cron target,
> endpoint and secret variable. Disable the old plugin, rename `platforms.hermes_assistant` and
> `HERMES_ASSISTANT_RPC_SECRET`, rewrite cron destinations and re-pair the phone.

## Delivered events and limits

- Completed/failed agent turns: a generic notice with the real stored session ID; tap opens that profile/session.
- Approval: a generic inbox notice. Upstream exposes a runtime session key rather than a guaranteed stored chat ID in this hook, so no fabricated chat link is sent. Open the active chat to review the actual approval.
- Cron/proactive sender: content available through the authenticated inbox; no inferred session link.
- No reasoning, response text, command, title, bearer secret or device secret goes to FCM. Only opaque event ID, device ID and protocol version are sent.
- Android displays an immediate private generic notice, then retrieves the event. The gateway may require a VPN; bounded WorkManager retries and foreground reconciliation recover deferred events without background polling.
- Up to 3 durable push attempts, each with bounded HTTP retries; exhausted events remain in the inbox until their 7-day TTL. Acknowledgement cannot be overwritten by a late FCM result. Token rotation cannot be revoked by an error for the previous token.
- Notifications depend on Google Play services, permission/channel settings and Android delivery conditions. A force-stopped app cannot receive until reopened. FCM delivery is not an exactly-once guarantee; stable notification IDs and event acknowledgements suppress duplicate alerts.

## Validation

```sh
HERMES_AGENT_SRC=/path/to/official/hermes-agent python -m pytest tests -q
```

Tests use synthetic devices/accounts and a local HTTP server, not real Firebase credentials. See the alpha12 delivery report for executed results. Real phone + Firebase + deployed gateway delivery still needs end-to-end testing with your configuration.

The plugin protocol and migration remain documented in [docs/protocol-v1.md](docs/protocol-v1.md). Legacy migration is explicit, never automatic.


## Conversational reminders (0.2.1)

With the platform enabled and at least one active paired device **in the same
profile**, the official `tool_request` middleware adds `hermes_android:home`
to new `cronjob` requests. This works for model-created reminders from Desktop,
Mobile and other surfaces that execute Hermes' normal tool pipeline. Existing
origin/Telegram/Discord/Bot Chat destinations remain in the delivery list.
The scheduler still owns timing, timezone, silent responses and failures; the
plugin adds no timer or background polling. Normal results reach the authenticated
mobile inbox and only opaque identifiers travel via FCM.

Explicit `local` remains an opt-out. `all` and existing mobile destinations are
not expanded again; a specific device is never widened to all devices. An update
that only changes a schedule/prompt does not overwrite the stored delivery route.
An explicitly supplied `failure_deliver: local` stays silent. Set the boolean
`platforms.hermes_android.mirror_reminders: false` to stop routing future requests;
this does not rewrite already scheduled jobs. Removing the plugin requires removing
its destinations from jobs that reference it.

**Coverage boundary:** this is not a global scheduler observer. Existing jobs and
jobs created directly through the scheduler's GUI/API bypass this middleware.
For those, set delivery to `origin,hermes_android:home` (or append
`,hermes_android:home` to their existing non-local destinations). No existing job
has been silently migrated. Upstream at the validated revision has no universal
cron-delivery plugin hook; `on_session_end` does not cover script-only jobs and the
execution ledger does not distinguish every intentional silence from local-only
output. A universal observer needs an upstream extension before we can promise
all-surface automatic coverage without patching Hermes.

The plugin must be installed/enabled in the profile used by Desktop, and the phone
must be paired with that profile. Firebase configuration and a real phone delivery
test are still required. No Android binary change is needed for protocol v1.
