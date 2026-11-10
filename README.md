# WavRead MCP Bridge

An independent, open-source MCP server and control script for Ableton Live, for AI-assisted music production.

> **Alpha.** Tested on Ableton Live 12.4.16 on macOS with Claude Code. Windows and other MCP clients are untested.
> **Unofficial:** not made, endorsed or supported by Ableton. Every edit to a Live Set is refused until you authorize
> that specific Set with a code shown in Live. Back up Sets you care about.

## What it does

It lets an AI assistant mix and route inside a running Live Set: return tracks and sends in exact dB, audio submix
buses with routing checks, devices and parameters in real units with read-back, racks, a Compressor sidechain,
automation, Arrangement clip edits, recording and level metering. Every write reports Live's value afterwards, so
nothing claims success it hasn't read back.

**MCP** ([Model Context Protocol](https://modelcontextprotocol.io)) is the open standard AI clients use to call
external tools. This project is an MCP server: your client (tested: Claude Code) starts it, and the assistant can
then call its 83 tools.

## How it works

```
AI client ──stdio──▶ MCP server (server/ableton_tooling_server.py)
                          │  JSON over TCP, 127.0.0.1:9878 only
                          ▼
                     Live control script (remote_script/WavReadBridge, runs inside Live)
                          │  Live Object Model, on Live's main thread
                          ▼
                     your open Live Set
```

- The control script is a Live "Control Surface" written in Python. It accepts connections from this computer only.
- It is written from scratch, and it isn't a fork. It uses the same message format as
  [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) and can run beside it (that one uses port 9877 for
  clips, notes and instruments), but it doesn't need it. Credits: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Requirements

| | |
|---|---|
| Ableton Live | 12 (tested: 12.4.16). Any edition with Control Surface support. Earlier 12.x versions are untested |
| Operating system | macOS (tested). Windows: untested, no install script |
| Runtime | [uv](https://docs.astral.sh/uv/), or Python 3.10+ with `mcp>=1.9,<2` |
| MCP client | Claude Code (tested). Any stdio MCP client should work but is untested |
| Optional | numpy, scipy, soundfile, pyloudnorm for the offline audio tools in `tools/` |

No third-party plugins are needed. The tests use only Live's own devices and Apple's built-in Audio Units.

## Install

1. **Get the code:** clone the repo, or download the source archive from the latest
   [release](https://github.com/EZmannBuilds/wavread-mcp-bridge/releases) and unzip it.
2. **Install the control script** (macOS):
   ```bash
   bash tools/install_remote_script.sh
   ```
   It copies `remote_script/WavReadBridge` to `~/Music/Ableton/User Library/Remote Scripts/WavReadBridge`
   (backing up any earlier copy under `backups/`).
3. **Enable it in Live:** restart Live, open Settings → Link, Tempo & MIDI, and pick **WavReadBridge** in an empty
   Control Surface slot, with Input and Output set to None. Live's status bar shows
   that the bridge is listening on port 9878.
4. **Add the MCP server to your client.** Claude Code:
   ```bash
   claude mcp add wavread-bridge -s user -- uv run -q --with "mcp[cli]>=1.9,<2" python /absolute/path/to/wavread-mcp-bridge/server/ableton_tooling_server.py
   ```
   Other clients: register a stdio server with that same command.
5. **Check the bridge:** ask the assistant to call `tooling_info`. It returns the control script's version, Live's
   version and the track count. "not listening" means step 3 didn't take: restart Live and pick the script again.

**Uninstall:** clear the Control Surface slot, run `bash tools/install_remote_script.sh --uninstall`, and remove the
server from your client (`claude mcp remove wavread-bridge -s user`).

## Safety: approve a Set before editing it

- **Read-only tools work on any open Set.** Every tool that changes a Set is refused until you approve that Set:
  1. The assistant calls `get_set_identity`, then `authorize_set` with the `file_path` and `set_id` it reported.
     That grants nothing on its own: Live's status bar shows a **6-character code**.
  2. You read the code from Live and give it to the assistant, which calls `confirm_authorization(code)`.
  - A code lasts 2 minutes and allows one attempt; a newer request replaces it; at most 3 requests a minute. The
    code never appears in any tool reply, error or log.
- **Approval ends** when you open or switch to another Set, Save As to a new path, reload the script, call
  `revoke_authorization`, or after 30 minutes without edits. Every newly opened Set starts read-only. Unsaved
  (untitled) Sets can't be approved: save first.
- **Turning codes off** (optional): after your first successful approval, the assistant asks once whether you want
  codes off. `set_approval_mode("off")` needs the open Set approved at that moment, so it costs one code read, and it's
  saved in `~/.wavread-bridge/settings.json`. `set_approval_mode("code")` turns codes back on at any time. With codes off,
  unsaved Sets and deletions outside a disposable Set are still refused.
- Every command is classified as read, meta, transport or write in `remote_script/WavReadBridge/policy.py`; anything
  not listed counts as a write. Starting playback while recording, or launching a clip that would record, counts as a
  write. Stop is always allowed. Deleting tracks, devices or clips also needs a disposable Set (one with a track
  named `__TOOLING_SCRATCH__`).
- **Limits, plainly:** the code is out-of-band confirmation for assistants that can't see your screen. An assistant
  with screen control could read it. Any program on your computer can reach port 9878 while the script is loaded,
  and anything that can edit your files can change the approval setting. Unload the script when you're not using it,
  and keep backups. See [SECURITY.md](SECURITY.md).

## Tools

83 tools in 12 groups. Full list with arguments: [docs/TOOL-REFERENCE.md](docs/TOOL-REFERENCE.md). Units and
conventions: [docs/TOOLS.md](docs/TOOLS.md).

| Group | Tools | Examples |
|---|---|---|
| Connection and inspection | 3 | `tooling_info`, `probe` |
| Write authorization | 6 | `get_set_identity`, `authorize_set`, `confirm_authorization`, `set_approval_mode` |
| Tracks and mixer | 6 | `list_tracks`, `create_track`, `set_mixer` |
| Return tracks and sends | 12 | `create_return_track`, `load_effect_on_return_track`, `set_track_send` |
| Routing and audio buses | 10 | `create_audio_bus`, `route_multiple_tracks`, `validate_routing` |
| Devices and parameters | 10 | `load_effect`, `set_device_parameter`, `snapshot_device` |
| Racks | 5 | `create_effect_rack`, `add_rack_chain`, `set_rack_macros` |
| Sidechain | 2 | `inspect_device_sidechain`, `set_sidechain` |
| Automation | 11 | `set_automation_points`, `get_automation`, `record_arrangement_automation` |
| Clips, audio and recording | 8 | `make_test_clip`, `create_audio_clip`, `record_track_audio` |
| Arrangement editing | 6 | `create_arrangement_midi_clip`, `split_arrangement_clip`, `move_arrangement_clip` |
| Transport, time and metering | 4 | `transport`, `set_song_time`, `measure_levels` |

## Examples

Tool calls as an assistant makes them. Each call is checked against the tools' real schemas in CI
(`tests/offline/test_readme_examples.py`), and the same operations pass in the Live end-to-end test. The calls
weren't run word for word in Live. Track references can be an index, `"track:N"`, `"return:A"`, `"master"` or an
exact name.

```text
# Inspect the current Set (read-only, no authorization needed)
tooling_info()
list_tracks(devices=true)
get_set_identity()             -> {"file_path": "/…/Demo.als", "name": "Demo", "set_id": "…"}

# Approve this Set for editing: Live shows a code, you read it out
authorize_set(file_path="/…/Demo.als", set_id="…")   -> "a code is shown in Live's status bar"
confirm_authorization(code="K7QX4P")

# Create an audio track and a MIDI track
create_track(kind="audio", name="Vocals")
create_track(kind="midi", name="Keys")

# Create a return track with an Echo, and send the keys to it at -12 dB
create_return_track(name="Delay")
load_effect_on_return_track(ret="A", effect="Echo")
set_return_device_parameter(ret="A", device="Echo", parameter="Feedback", value="35 %", units="display")
set_track_send(track="Keys", send="A", db=-12)

# Route two tracks into a new audio bus, then check the routing
create_audio_bus(name="Music Bus", sources=["Keys", "Vocals"])
validate_routing()

# Insert an effect on a track and adjust a parameter
load_effect(track="Vocals", effect="EQ Eight")
set_device_parameter(track="Vocals", device="EQ Eight", parameter="1 Frequency A", value="120 Hz", units="display")

# Create a MIDI clip in the Arrangement
create_arrangement_midi_clip(track="Keys", at="1.1.1", length=16, notes=[[48, 0, 4, 100], [55, 8, 4, 100]])

# Automation in a session clip: a volume dip over 8 bars
make_test_clip(track="Keys", slot=0, length=32, notes=[[60, 0, 4, 100]])
set_automation_points(track="Keys", slot=0, target={"mixer": "volume"}, units="display",
                      points=[{"at": "1.1.1", "value": "0 dB"}, {"at": "3.1.1", "value": "-12 dB"},
                              {"at": "5.1.1", "value": "0 dB"}])
validate_automation(track="Keys", slot=0, target={"mixer": "volume"}, units="display",
                    expect=[{"at": "1.1.1", "value": "0 dB"}, {"at": "3.1.1", "value": "-12 dB"},
                            {"at": "5.1.1", "value": "0 dB"}])
```

## What is tested

Full evidence per feature: [docs/CAPABILITY-MATRIX.md](docs/CAPABILITY-MATRIX.md).

- **Offline (CI, no Live):** 58 tests. They cover the write policy and approval codes (including a check that every
  command is classified, and that a code never appears in a reply or log), the message protocol against a fake control
  script, errors and fragmented replies, the tool docs and README examples, the audio tools, and install and uninstall.
- **In Live (12.4.16, macOS, a disposable Set):** `tests/test_e2e_release.py`, version 0.4.0, every phase passing.
  - refuse: 17 of 17. Edits are refused while unapproved, including a direct TCP connection that skips the MCP server,
    wrong and expired codes, and a pending request.
  - Codes read by a person: a replaced code refused, the right code granted, a replayed code refused, a code dead
    after a Set switch.
  - write: 15 of 15, covering tracks, returns, a native effect, an Apple AU, sends, bus routing, MIDI clips,
    Arrangement edits, automation and error handling.
  - switched Sets: 2 of 2. reopened: 7 of 7. re-approved: 2 of 2. untitled Sets: 3 of 3.
  - Transport: launching an armed clip and continuing with record on are refused; stop is allowed.

**Working (proven in Live):** returns and sends in dB, audio buses and routing checks, device loading and parameters,
snapshots, Session automation, Arrangement automation by real-time recording, a Compressor sidechain, racks and chain
mixing, recording and resampling, warp and pitch, and Arrangement move, copy, trim and split.

**Experimental or partial:** parameters of large third-party plugins (they need a one-time configure step,
Live's Configure step), other devices'
sidechains, third-party presets and take lanes. The saved-set editing tools from development (plugin parameter
slots, rack macro mapping) are not part of this release.

## Known limitations

- **No Export Audio tool.** Live's API has no export call. Workaround: `record_track_audio` resamples the Main for
  exact bars, and `tools/audio_check.py` measures the file (LUFS, true peak, clipping, loop seam).
- **No groove or MIDI velocity editing** yet.
- Arrangement automation can only be recorded in real time, not drawn. Curve tension has no effect on Live 12.4.
- No native Group Track creation; reordering or deleting rack chains and saving rack presets aren't possible through
  the API.
- Fades and reverse are offline only (`tools/wav_reverse.py`).
- Windows and MCP clients other than Claude Code are untested.

Planned work: [ROADMAP.md](ROADMAP.md).

## Development

- Offline tests:
  ```bash
  uv run --with "mcp[cli]>=1.9,<2" --with numpy --with soundfile --with pyloudnorm --with scipy --with pytest pytest tests/offline
  ```
- Live tests: open a disposable Set (add a track named `__TOOLING_SCRATCH__`), then run
  `python3 tests/test_e2e_release.py refuse|write|switched|reopened|reapproved|untitled`. Each `tests/test_*.py` lists what it needs.
- See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT © 2026 Erik Mann. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Ableton, Live and Push are trademarks of Ableton AG. WavRead MCP Bridge is an independent project and is not
affiliated, associated, authorized, endorsed by, or in any way officially connected with Ableton AG.
