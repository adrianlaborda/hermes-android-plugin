# Changelog

All notable changes to the `hermes-android` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.4] - 2026-10-22

### Added

- The phone is the primary channel for reminders. A reminder made outside a messaging channel (Desktop, TUI, CLI, API or
  the app) goes to the phone only, instead of `origin`, which Hermes resolves to the first messaging home channel such
  as Telegram. Reminders made in Telegram still notify their own chat. Turn it off with
  `platforms.hermes_android.primary_channel: false`, or with `/android-primary-channel [profile] [on|off]`, which the
  app can call to show and change the setting.

### Fixed

- Finished turns and approval requests from Hermes Mobile chats did not notify the phone with the default
  `notify_turns: non_messaging`, because the app's chats counted as a messaging channel. They notify now.
- Reminders were not routed to the phone on Hermes 0.22 and later, which renamed the `cronjob` tool to `cronjob_manage`.
  They stayed on `origin`, which falls back to the first messaging home channel, such as Telegram. Both tool names are
  routed now.
- A reminder asked in a Hermes Mobile chat goes to the phone only. It no longer also targets `origin`, which has no
  chat of its own in the app.

## [0.5.3] - 2026-10-15

### Fixed

- Approval notices fired for every check of Hermes' smart-approval guardian, which decides on its own. They also
  fired for each duplicate request, so the phone kept buzzing with approvals that were never waiting for anyone. Only
  real prompts notify now.
- An approval answered elsewhere (Desktop, Telegram) or timed out is withdrawn from the phone.
- A notice Hermes fired twice for the same turn or tool call is pushed once.

### Added

- Approval notices carry the chat title and what the action does, and open that chat.
- `platforms.hermes_android.notify_approvals`: `all`, `non_messaging` (default) or `never`.

## [0.5.2] - 2026-10-14

### Fixed

- Newer Hermes Agent releases build each plugin's environment with Python 3.14. The plugin declared
  `requires-python < 3.14`, so Hermes refused it and disabled it on update. It now supports Python 3.11 and later.

## [0.5.1] - 2026-10-13

First public release.

### Added

- `/android-enable <profile>` enables the plugin for another profile and brings it up live. With
  `gateway.multiplex_profiles`, only that profile restarts inside the gateway. Hermes Mobile calls it from
  **Notifications → Enable for this profile**.
- `/android-pair <profile>` and `/android-test <profile>` answer for the named profile. A profile that has not enabled
  the plugin gets `plugin_enabled: false` and the profile that can enable it.

### Changed

- Enabling a profile links the plugin into it instead of copying it, so one install and one update serve every
  profile. An older copy is kept as a backup.
- Every profile shares the same Firebase key file.
- Hermes Mobile conversations count as a non-messaging surface, so the app's setup commands work there.

### Fixed

- Secondary profiles of a multiplexing gateway report the shared API server, so they can pair.

## 0.5.0 - 2026-10-12

### Added

- `hermes_android_profiles` and `hermes_android_enable_profile` set up other profiles from chat.
  `hermes_android_route_crons` takes an optional `profile`.
- Turn notices carry the chat title and an excerpt of the answer. Both are stored in the inbox only, never sent
  through FCM.
- `platforms.hermes_android.notify_turns`: `all`, `non_messaging` (default) or `never`.

### Fixed

- Setup no longer counts the launch profile's environment as another profile's secret.

## 0.4.0 - 2026-10-12

### Added

- Guided setup:
  - the `hermes-android:setup` skill;
  - the tools `hermes_android_status`, `_configure`, `_install_credentials`, `_route_crons` and `_send_test`;
  - the app-facing commands `/android-pair`, `/android-credentials`, `/android-test` and `/android-status`.
- The service-account key is re-read on every send, so a new or rotated key needs no restart.

## 0.3.0 - 2026-10-12

### Changed

- Renamed from `hermes-assistant` to `hermes-android`: the plugin, the platform `hermes_android`, the `HERMES_ANDROID_*`
  variables and `plugin-data/hermes-android/`. There is no behavior change. See the upgrade note in the README.

## 0.2.1 - 2026-10-03

### Added

- New conversational `cronjob` requests also deliver to the phone, through the `tool_request` middleware.

[Unreleased]: https://github.com/adrianlaborda/hermes-android-plugin/compare/v0.5.4...HEAD
[0.5.4]: https://github.com/adrianlaborda/hermes-android-plugin/releases/tag/v0.5.4
[0.5.3]: https://github.com/adrianlaborda/hermes-android-plugin/releases/tag/v0.5.3
[0.5.2]: https://github.com/adrianlaborda/hermes-android-plugin/releases/tag/v0.5.2
[0.5.1]: https://github.com/adrianlaborda/hermes-android-plugin/releases/tag/v0.5.1
