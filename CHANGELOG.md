# Changelog

## v0.5.0-alpha.1 (2026-11-10)

- **Approval codes removed.** Tools now edit whichever saved Set is open, with no approval step. `authorize_set`,
  `confirm_authorization`, `set_approval_mode` and `revoke_authorization` are gone (79 tools). Unsaved Sets are still
  refused, deletions still need a disposable Set, recording through transport still counts as a write, and stop
  always runs. Work on copies of Sets that matter.
- In Live (12.4.16, macOS): connection 4/4 and the delete guard 3/3 pass. The full edit suite last passed under 0.4.0.

## v0.4.0-alpha.1 (2026-11-10)

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
