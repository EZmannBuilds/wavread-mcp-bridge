# Changelog

## v0.4.0-alpha.1 (unreleased)

First public release, as WavRead MCP Bridge. An experimental developer preview.

- Write protection: every Live Set opens read-only, and edits need that Set to be approved. One central classifier
  covers every command; unknown commands count as writes. Approval ends on a Set switch, Save As or reload.
- Input checks: loopback-only connections, a 1 MB request cap, validated command names, parameters and audio paths.
- Edits need a one-time code that Live shows in its status bar (`authorize_set`, then `confirm_authorization`).
  Codes can be turned off after one approval (`set_approval_mode`). Untitled Sets are refused, recording through
  transport counts as a write, and an approval idles out after 30 minutes.
- The control script is named WavReadBridge; env vars `WAVREAD_BRIDGE_HOST` / `WAVREAD_BRIDGE_PORT`.
- 83 MCP tools for returns and sends, routing and audio buses, devices and parameters, racks, sidechain, automation,
  clips and recording, Arrangement editing, and metering.
- Offline test suite in CI; end-to-end tests in Live 12.4.16 on macOS.
