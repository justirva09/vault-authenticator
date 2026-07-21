# CHANGELOG


## v0.3.0 (2026-07-21)

### Bug Fixes

- Bundle certifi CA bundle for updater HTTPS requests
  ([`ab3263d`](https://github.com/justirva09/vault-authenticator/commit/ab3263d2684df28e0a12fad6c596b7feb2e56504))

PyInstaller-frozen builds don't reliably inherit the OS CA trust store, so the update checker's
  urllib calls failed with CERTIFICATE_VERIFY_FAILED in the field (confirmed on a packaged v0.2.0
  build). Explicit ssl.create_default_context(cafile=certifi.where()) fixes it.

### Features

- Show app version in a footer
  ([`589ca79`](https://github.com/justirva09/vault-authenticator/commit/589ca7987bb7be679adb994ed21b31c8e5d40a26))

Fixed bottom footer displaying the running version (from /api/status), so the installed build is
  visible at a glance in the app itself.


## v0.2.0 (2026-07-21)


## v0.1.0 (2026-07-21)

### Bug Fixes

- Correct semantic-release config (build_command type, allow_zero_version)
  ([`bab70c3`](https://github.com/justirva09/vault-authenticator/commit/bab70c33ae5cc9e12dac2385c6b817df5a211414))

### Documentation

- Add auto-updater design spec
  ([`5148eed`](https://github.com/justirva09/vault-authenticator/commit/5148eed00ed561441956e2a810898d65037ac6bf))

Spec for cross-platform (macOS/Windows/Linux) self-update: GitHub release check on startup,
  checksum-verified background download, and platform-specific swap+relaunch (direct rename on
  mac/Linux, helper script on Windows to work around file locking).

- Add auto-updater implementation plan
  ([`7d511cc`](https://github.com/justirva09/vault-authenticator/commit/7d511cc2b7270ab1595df6f511f885df4a76fdfc))

5-task TDD plan: core updater module, Flask routes, frontend banner, CI checksum publishing, manual
  cross-platform verification.

### Features

- Add cross-platform auto-updater
  ([`57ca234`](https://github.com/justirva09/vault-authenticator/commit/57ca234aead2070dac4e0e739c32c35308fbc6a7))

Checks GitHub releases on startup, downloads and checksum-verifies the matching platform build in
  the background, then swaps it into place and relaunches - direct rename on macOS/Linux, helper
  .bat retry-loop on Windows to work around file locking. CI now publishes a per-asset .sha256
  alongside each release archive.

19 tests passing (pytest).

- Initial release of Vault Authenticator
  ([`224e216`](https://github.com/justirva09/vault-authenticator/commit/224e216ef1fb115497dc620bc18098d4369a5301))
