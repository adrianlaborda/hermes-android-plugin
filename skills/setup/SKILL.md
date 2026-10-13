---
name: setup
description: Set up or troubleshoot push notifications for the Hermes Mobile Android app (Firebase Cloud Messaging, pairing, cron delivery). Use when the user asks for phone/Android notifications, reminders on the phone, or why notifications do not arrive.
---

# Hermes Android notifications: guided setup

You are helping the user receive Hermes notifications on their phone through the Hermes Mobile
app. Notifications cover finished or failed turns, approval requests, reminders, and scheduled
(cron) jobs, just as Telegram receives them. Each user brings **their own Firebase project**.
There is no shared relay.

Talk to the user in their language, one step at a time, and wait for confirmation before moving
to the next step. Keep instructions short and concrete. The user is probably on their phone.

## Hard rules

- **Never ask the user to paste or attach the Firebase service-account key in the chat.** Chat
  attachments are expanded into the prompt, so the private key would reach the model provider.
  The key goes in through the app's **Upload server key** button, or onto the server by scp
  followed by `hermes_android_install_credentials`.
- Never print, read or summarize key files, `.env` or the pairing secret. The tools never return
  them, so do not try to obtain them another way.
- Enabling the API server exposes the agent on the network. If `hermes_android_status` reports it
  disabled, explain this and get explicit consent first. Bind it to a LAN or VPN address only,
  never a public one, and make sure `API_SERVER_KEY` is strong.
- Restart the gateway only after telling the user. Telegram and other channels drop for a few
  seconds.

## Procedure

1. **Diagnose.** Call `hermes_android_status`. Its `next_steps` tells you where you are. Re-run it
   after every step.

2. **Server side.** If `platform_enabled` is false or `pairing_secret` is not `ok`, call
   `hermes_android_configure`. Then restart the gateway with `hermes gateway restart` (terminal
   tool, if available). Otherwise ask the user to run it on the server.
   - If the API server is off or bound to loopback, see the hard rules. Its settings are
     `API_SERVER_ENABLED=true`, `API_SERVER_HOST=<LAN/VPN IP>`, `API_SERVER_PORT=8642` and a
     strong `API_SERVER_KEY` in the profile's `.env`, followed by a restart.

3. **Firebase project.** The user does this in a browser:
   1. Open <https://console.firebase.google.com>, then **Create a project** (Google Analytics is
      not needed). Reusing an existing project is fine.
   2. Open **Project settings** (gear icon), then **General**, then **Your apps**, then
      **Add app**, then **Android**.
      - **Android package name:** the exact package shown in the app under **Notifications**.
        The app has a copy button. A different package will not work.
      - Leave nickname and SHA-1 empty, then **Register app**.
      - **Download google-services.json.** Skip the remaining SDK steps; the app is already
        built with the SDK.
   3. Open **Project settings**, then **Service accounts**, then **Generate new private key**.
      This downloads a JSON file. It is a secret: tell the user so.
   4. Optionally check **Project settings → Cloud Messaging**, where *Firebase Cloud Messaging
      API (V1)* should be *Enabled*. It is enabled by default on new projects.

4. **Phone.** In Hermes Mobile, open the menu, then **Notifications**:
   1. **Import google-services.json** and pick `google-services.json`.
   2. **Upload server key** and pick the service-account JSON. The app sends it to this server
      over its authenticated connection. It never enters the chat.
   3. Allow notifications when Android asks, then tap **Pair with this server**.
   - If the app shows another profile, the user must first select the profile this setup is for.
     Each profile pairs separately.

5. **Verify.** Call `hermes_android_status`: `firebase_service_account.state` should be `ok` and
   `devices.active` at least 1. Then call `hermes_android_send_test` and ask whether the
   notification arrived. Outcomes:
   - `success`: FCM accepted it. If nothing shows on the phone, check Android notification
     settings and battery restrictions for the app.
   - `auth`: the key belongs to a different project than `google-services.json`, or FCM v1 is
     disabled.
   - `permanent`: the device token is stale. Re-pair from the app.

6. **Scheduled jobs.** Call `hermes_android_route_crons` with `apply=false`, show the user which
   jobs would also notify the phone, and apply only if they agree (`apply=true`). New reminders
   created by talking to you include the phone automatically. Jobs created directly in the
   dashboard do not; add `hermes_android:home` to their delivery.

## Other profiles

Hermes isolates profiles: each one enables its own plugins and has its own pairing secret, inbox, devices and
cron jobs. The plugin is installed once and linked into each profile, so an update reaches all of them, and every
profile sends through the same Firebase key file. The app's Notifications screen sends the user here when a
profile is not enabled yet. When the user asks to use the app with another profile (for example "activate
notifications for my work profile"):

1. Call `hermes_android_profiles` to show the current state of every profile.
2. Call `hermes_android_enable_profile` with `profile=<name>` and `apply=false`, show the plan, and apply with
   `apply=true` once the user confirms. It links the plugin (an old separate copy is replaced and kept as a
   backup) and points the profile at this profile's Firebase key, because the phone has a single Firebase
   project. Nothing has to be uploaded again.
3. Applying brings the plugin up live: it loads in the chat backend and restarts only that profile inside the
   multiplexing gateway, so the other profiles and their channels keep running. Restart the whole gateway
   (with consent) only if the result says `restart_required`.
4. In the app, the user opens **Notifications**, picks that profile at the top and taps **Pair with this server**.
   The app can also do steps 2–4 by itself: on a profile that is not enabled, **Enable for this profile**
   runs `/android-enable <profile>` in a profile that has the plugin, then pairs.
5. Optionally call `hermes_android_route_crons` with `profile=<name>` to route that profile's scheduled jobs.

## What gets notified

- **Scheduled jobs and reminders** delivered to `hermes_android:home`, which carries the job's own output.
- **Finished or failed turns**: the title is the chat title and the body is an excerpt of the answer. By default
  only turns from non-messaging surfaces notify, so turns from the app, Desktop or the API do, but turns from
  Telegram and similar do not, because that channel already told the user. Change it with
  `platforms.hermes_android.notify_turns`: `all`, `non_messaging` (default) or `never`.
- **Approval requests.**

FCM only ever carries an opaque event ID. The phone fetches the title and body from this server. Whether the content
shows on the lock screen is the user's choice in the app.

## Troubleshooting quick reference

| Symptom | Likely cause |
|---|---|
| App says the server is not ready | API server off or loopback; secret missing; gateway not restarted after `hermes_android_configure` |
| App cannot reach the server | Phone not on the LAN/VPN; firewall blocks the API server port (default 8642) |
| `auth` on test | Key and `google-services.json` from different Firebase projects |
| App says "Firebase rejected this phone's registration" | The project's Android API key has a restriction that blocks the app, usually *Websites (HTTP referrer)*. In Google Cloud Console → APIs & Services → Credentials → *Android key (auto created by Firebase)*, set Application restrictions to *None*, or to *Android apps* with the app's package and signing SHA-1. Then pair again. |
| Works on Wi-Fi only | API server reachable only on the LAN; use a VPN such as WireGuard or Tailscale for remote access |
| Telegram replies also notify the phone | `notify_turns` is set to `all`; the default `non_messaging` skips them |
