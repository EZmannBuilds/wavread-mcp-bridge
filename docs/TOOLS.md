# ableton-tooling: tool reference

Server: `ableton-tooling` (registered with your MCP client; see the README). It talks to the WavReadBridge Remote Script on 127.0.0.1:9878.
The `ableton` server (port 9877) keeps clips, notes, browser browsing and composing. Use this server for mixer,
returns, sends, routing, buses and device chains.

Tool names in a session: `mcp__ableton-tooling__<tool>`. Call `tooling_info` first: if it fails with "not listening",
WavReadBridge isn't loaded in Live (see Setup).

## Write permission (0.5.0): read this first

- **No approval codes.** 0.3.0 and 0.4.0 asked for a one-time code before editing a Set. the owner removed it on
  2026-11-10 ("Will other people have to run the code? If so just remove it").
- **Read-only tools work on any open Set.** Tools that change a Set work on any **saved** Set:
  - untitled Sets are refused ("save the Set first"), so every edit lands in a file the user can find and back up;
  - deletes (`delete_track`, `delete_device`, `delete_arrangement_clip`) run only in a disposable Set (a track named
    `__TOOLING_SCRATCH__`);
  - playback while record mode or Session record is on, and launching a clip that would record, count as edits;
    `stop` and `stop_all_clips` always run.
- `get_set_identity` → `file_path`, `name`, `set_id` (a random id stored inside the Set). `write_status` →
  `writes_allowed` (true for any saved Set) and `scratch_set`.
- **Every command is classified** in `remote_script/WavReadBridge/policy.py` as read, meta, transport or write. Any
  command not listed is a write.
- **Inputs are checked:** connections from anything but this computer are dropped, and requests over 1 MB are
  refused. Command names, parameter types and nesting are validated, and audio paths must be absolute, without `..`,
  an existing file, and an audio type.
- **Ask before editing a song that matters, and suggest a backup.** Nothing in the bridge asks for the user's OK any
  more; the assistant has to.
- Tests: `python3 -m unittest discover -s tests/offline` (no Live needed) and `tests/test_e2e_release.py
  connection|write|notscratch|reopened|untitled`.

## Conventions

- **Track refs**: `0` / `"track:0"` (song.tracks), `"return:A"` / `"return:0"` / `"return:Reverb"` (song.return_tracks),
  `"master"`, or an exact name. An ambiguous name is an error, never a guess.
- **Device refs**: an index in the chain or an exact device name. **Parameters**: an exact name (or original name), or an index.
- **Units**:
  - `db` and `volume_db` are dB as Live displays them. `pan` runs -50 (50L) to 50 (50R).
  - `units="display"` means display units: dB, Hz, ms, %, the way Live shows the number. Seconds and kHz strings are converted ("1.2 s" means 1200 ms).
  - `units="raw"` means the internal `value` (min..max).
  - `"auto"`: a string is a display value or a quantized item, a number is raw.
- Every write returns before and after read-back and the method used (`display_value`, `bisect`, `raw`, `item`).
  Check `after.display`: it is what Live shows.
- **Live's routing lists fill on the next tick after a track is created.** Routing tools retry for about 1.5 s.
- **Destructive tools** (`delete_track`, `delete_device`, `set_bus_effect_chain(replace=True)`) run only in a set that
  has a track named `__TOOLING_SCRATCH__`.

## Returns (priority 1)

| Tool | Arguments | Notes |
|---|---|---|
| `list_return_tracks` | none | Letter, name, fader, devices, output, and which tracks feed each return |
| `create_return_track` | `name?` | Appends a return. Reuse A-Reverb and B-Delay where they fit |
| `rename_return_track` | `ret`, `name` | `ret`: "A" / "return:A" / its name |
| `get_return_track_devices` | `ret`, `params=False` | Includes rack chains |
| `load_effect_on_return_track` | `ret`, `effect`, `position?` | `effect`: a native name ("Echo", "Hybrid Reverb") or a browser URI ("query:Plugins#VST3:MeldaProduction:MCompressor") |
| `get_return_device_parameters` | `ret`, `device` | |
| `set_return_device_parameter` | `ret`, `device`, `parameter`, `value`, `units` | |
| `set_return_volume` | `ret`, `db` | |
| `inspect_return_routing` | `ret` | Output, choices, its own sends, feeders |
| `get_track_sends` | `track` | |
| `set_track_send` | `track`, `send`, `db` or `value` | `db=None` or "-inf" turns the send off |
| `send_curve` | `track`, `send`, `points` | Live's own raw → display table |

Example (`B` is the return's letter, "Echo" its device):

```
load_effect_on_return_track(ret="B", effect="Echo")
set_return_device_parameter(ret="B", device="Echo", parameter="Feedback", value=30, units="display")
set_track_send(track="Keys", send="B", db=-14)
```

## Mixer

`set_mixer(track, volume_db?, pan?, mute?, solo?)`: tracks, returns and the master (volume and pan only).

## Buses and routing (priority 2)

| Tool | What it does |
|---|---|
| `create_audio_bus(name, sources?, volume_db=0, index=-1, monitoring="in")` | Creates an audio track with Input "No Input", Monitor "In" and Output "Main", routes each source's output into it, then reports routing problems |
| `route_track_to_bus(track, bus)` / `route_multiple_tracks(tracks, bus)` | Sets each output by the routing type's attached track. Reverts and errors on a feedback loop |
| `set_bus_volume(bus, db)` | |
| `set_bus_effect_chain(bus, chain, replace=False)` | `chain`: `[{"effect": "Glue Compressor", "params": {"Threshold": "-18 dB"}}, "Saturator"]` |
| `get_routing(track)` / `set_routing(track, direction, target, channel?)` / `set_monitoring(track, state)` | Low level. `target` is a choice Live offers, or a track ref |
| `get_routing_graph()` / `validate_routing()` | Loops, double routing to Main, silent buses (monitor Off, No Output, muted, -inf), soloed buses |

A **return** (fed by sends), an **audio bus** (fed by outputs) and a **native Group Track** are three different things.
Group Tracks can't be created by these tools (the 12.4 LOM has no call for it).

## Devices (priority 4)

**Inside racks**: `get_device_parameters`, `set_device_parameter` and `set_device_parameters` (0.1.1+) take
`device=<the rack on the track>`, `chain="0"` (the rack's chain 0) and `chain_device=0` (device 0 in that chain).
In 0.1.1 the path can go deeper: `chain="1/0/2"` is chain 1, its device 0 (a nested rack), that rack's chain 2.

`get_track_devices`, `load_effect(track, effect, position?)`, `get_device_parameters`, `set_device_parameter`,
`set_device_parameters(values={name: value})` (every name is checked before any write), `set_device_on` (bypass),
`move_device`, `delete_device` (scratch sets only), `snapshot_device(save_to?)`, `restore_device_snapshot(snapshot_path)`.

## Live behaviour to respect (measured 2026-11-10, `docs/UNITS.md`)

- A track's own output meter reads **before** its mute and solo. Judge a mute by the main or the bus it feeds.
- **Solo overrides mute**: a soloed, muted track still plays.
- Sends are post-fader.
- Meters hold peaks about 1 s, so wait 2 s after a change before `measure_levels`.

## Python client (for your own scripts)

```python
import sys; sys.path.insert(0, "/path/to/wavread-mcp-bridge/tests")
from lt import call, load          # call("<command>", **params) -> dict; raises LiveError on failure
call("set_track_send", track="Keys", send="C", db=-12)
```

The command names are those of the Remote Script (`info` lists them). The MCP tools above wrap the same commands.

## Proof and test material

- `measure_levels(tracks?, seconds=4)`: peak dBFS per track while Live plays. None means silent (≤ -70 dBFS).
- `transport(action)`, `make_test_clip(track, notes)`, `fire_clip`.

## Setup and rollback

- Install: `tools/install_remote_script.sh` (done 2026-11-10). Then, in Live → Settings → Link, Tempo & MIDI, pick
  **WavReadBridge** in an empty Control Surface slot (Input and Output: None). Live shows "WavReadBridge: listening on port 9878".
- Rollback: clear that slot, then run `tools/install_remote_script.sh --uninstall` and `claude mcp remove ableton-tooling -s user`.
  AbletonMCP and the `ableton` server are never modified.
- Regression and calibration tests: `tests/test_returns.py build|verify [--reopened]`, `tests/test_buses.py` and
  `tests/test_plugins.py`, each run in a scratch set.

## Phase 2 (ext.py; full status in docs/CAPABILITY-MATRIX.md)

- **Automation:**
  - `list_automatable_parameters`, `set_automation_points`, `set_automation_curve`, `get_automation`,
    `copy_automation`, `delete_automation` and `validate_automation` (Session clips);
  - `record_arrangement_automation` (Arrangement, recorded in real time), `param_state`, `re_enable_automation`,
    `back_to_arrangement`;
  - `capture` (meters and parameters inside Live, at about 10 Hz).
- **Sidechain:** `inspect_device_sidechain`, `set_sidechain`.
- **Racks:** `create_effect_rack`, `add_rack_chain`, `insert_device_in_chain`, `set_chain_mixer`,
  `set_rack_macros`. Macro → parameter mapping uses a saved-set edit tool (not in the public release) (saved-set edit).
- **Clips and recording:** `get_clip`, `set_clip`, `warp_marker`, `create_audio_clip`,
  `duplicate_to_arrangement`, `record_track_audio` (resample; also the dialog-free render), `set_arm`,
  `set_song_time`.
- **Offline tools:**
  - `tools/audio_check.py` (duration, rate, peak, true peak, LUFS, clipping, silence, loop seam);
  - `tools/wav_reverse.py`;
  - `tools/ab_compare.py` + `tools/ab_analyze.py` (A/B with loudness-matched copies);
  - a saved-set edit tool (not in the public release) (expose a large plugin's parameters, e.g. Vital AU);
  - a saved-set edit tool (not in the public release).
- After editing `ext.py`: `tools/install_remote_script.sh --ext`, then `reload_extensions`. No Live restart.
