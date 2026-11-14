# Changelog

## v0.6.0-alpha.1 (unreleased)

- **Renamed to Faderhand, for Ableton Live 12.** The control script folder and class are now `Faderhand`
  (status bar: "Faderhand: listening on port 9878"), `tooling_info` reports name `Faderhand` and version `0.6.0`,
  the MCP server id is `faderhand`, and the docs, issue-template links and security advisory URL point to
  https://github.com/EZmannBuilds/faderhand. Tool behavior, port, safety guards and the server file path
  (`server/ableton_tooling_server.py`) are unchanged.
- **Back-compat.** `tools/install_remote_script.sh` installs `Faderhand` and also updates an already existing
  `WavReadBridge` folder, so an old Control Surface slot keeps listening on 9878 (enable only one of the two).
  The server reads `FADERHAND_HOST` / `FADERHAND_PORT` first, then falls back to `WAVREAD_BRIDGE_HOST` /
  `WAVREAD_BRIDGE_PORT`. Existing `claude mcp add wavread-bridge` configs keep working until removed. The Set
  identity key (`wavread.set_id`) is unchanged so earlier Sets keep their identity.

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
