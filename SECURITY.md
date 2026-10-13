# Security policy

## Supported versions

Only the latest release gets security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/adrianlaborda/hermes-android-plugin/security/advisories/new).

Include what an attacker can do, the steps to reproduce and the plugin and Hermes Agent versions. You will get an
answer within a week. Once a fix is released, the advisory is published and you are credited unless you prefer
otherwise.

## Scope

The things this plugin must protect:

- **The device RPC endpoint.** Every request is authenticated with the profile's pairing secret and the device's own
  secret.
- **The Firebase service-account key.** It is stored owner-only and is never printed, returned to the model or sent
  through chat.
- **Notification content.** Only an opaque event ID, the device ID and the protocol version go through FCM. The content
  stays in the server's inbox.
- **Setup commands.** `/android-pair` and `/android-credentials` refuse to answer in messaging channels.
