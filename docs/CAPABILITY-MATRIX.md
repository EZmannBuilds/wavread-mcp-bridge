# Ableton capability matrix, Phase 2 (Live 12.4.16, WavReadBridge 0.2.0; 2026-11-10)

Status:
- **Working**: performed in Live, read back, persisted through save and reopen where that applies, and proven
  audible where that applies. The test is named.
- **Partial**: works with a stated limit.
- **Untested**: built, not yet proven in Live.
- **Missing**: not built yet.
- **Unsupported**: the LOM can't do it; the alternative route is named.

Route: LOM (direct API), REC (real-time recording through the LOM), ALS (validated saved-set editing), UI (screen
automation), OFF (offline file processing).

## Automation (priority 1)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| list automatable parameters (mixer, devices, rack chains) | Working | LOM | `list_automatable_parameters` |
| Session clip envelopes: points (ramp/step), shapes (ramp, fade, sweep, hold, pulse, sine; linear/ease/exp/log) | Working | LOM | `tests/test_automation_session.py`: native Auto Filter and Vital, 8 bars |
| musical time (bar.beat.sixteenth → beats, no drift) | Working | — | values land on the intended bars to 1e-4 beat |
| read, copy, delete, validate (incl. loop wrap) | Working | LOM | wrap jump 0.0 |
| mixer volume, pan, sends, rack-chain device params, macros | Working | LOM | volume dip, reverb send rise and reset tested |
| Vital parameters | Working (after configuring) | ALS + LOM | **Vital 1.6.4 (universal) installed 2026-11-10 with the owner's yes: Live now lists and runs the VST3 natively**, with values in Vital's units ("69.6 semitones"); the cutoff measured −39.2 → −6.2 dB. The same IDs configure AU and VST3. The VST3 ignores @values (it restores its own state). Before that: Vital 1.0.7 was Intel-only, so Live loads only its AU, with 772 parameters hidden. a saved-set edit tool (not in the public release) adds them to the Configure list; then the cutoff is automatable: −51.8 → −10.0 dB measured |
| playback follows the envelope | Working | LOM + capture | in-Live capture at about 10 Hz |
| rendered audio reflects automation | Working | REC + OFF | Main resampled; per-bar RMS rises over bars 1–6, holds in 7, falls through 8 |
| persists through save and reopen | Working | — | Session and Arrangement, native and Vital |
| Arrangement automation | Working | REC | `record_arrangement_automation`: lanes can't be drawn through the LOM; recorded in real time instead, and playback matches to 0.005. `tests/test_automation_arrangement.py` |
| curve tension (control_coefficients) | Unsupported | — | no effect on 12.4.x; use dense ramp points (`curve=`) |
| copying session envelopes into the Arrangement | Unsupported on instrument tracks | — | measured: `duplicate_clip_to_arrangement` drops them; use REC |

## Routing and sidechain (priority 2)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| returns, sends in dB, buses, routing graph | Working | LOM | Phase 1 tests, re-run after reopen |
| Compressor sidechain: inspect, set source, S/C params | Working | LOM | `tests/test_sidechain.py`: 12.1 dB ducking on the beat; 1.6 dB with no trigger; 0.09 dB with S/C off; survives reopen |
| own-track sidechain refused | Working | — | — |
| other devices' sidechain source (Glue, Gate, Auto Filter, Multiband) | Untested on 12.4.16 | LOM | livebridge reports no routing on 12.4.5; check with `inspect_device_sidechain` |
| parallel effects bus | Working | LOM | an Echo return fed by sends, audibly measured (`test_returns.py`); a parallel rack (below) |

## Racks (priority 3)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| create Audio Effect / Instrument / MIDI / Drum Rack, add chains, insert devices in chains | Working | LOM | an 808 rack (Clean; EQ Eight HP 48 dB at 150 Hz plus Saturator); survives reopen |
| chain volume, pan, on/off | Working | LOM | blend −12.4 dB against −15.2 dB clean: no cancellation |
| show macros, set macro values | Working | LOM | — |
| map a macro to a parameter | Working | LOM marks + ALS | a saved-set edit tool (not in the public release): mark the target with a sentinel display value through the LOM, save, then the tool writes a `<KeyMidi>` block (channel 16, controller = macro index) and the range into a copy of the set and places the macro at the restored value. Tested: Grit → Saturator Drive 0–24 dB inside a rack chain; +4.7 dB audible; survives Live's own save and reopen |
| delete, reorder or duplicate chains; save a rack preset | Unsupported | UI / ALS | — |

## Resampling and audio editing (priority 4)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| record a track's output or the Main (Resampling) for exact bars | Working | LOM | `record_track_audio`: `fire(record_length)` works on 12.4.16; 8 beats exact |
| audio clip from file (Session slot or Arrangement) | Working | LOM | `create_audio_clip` |
| pitch coarse/fine, gain, warp on/off, warp mode, markers, loop | Working | LOM | survive reopen; the start marker is written while looping (Live ignores it otherwise) |
| warp markers add/move/remove | Working | LOM | — |
| reverse | Unsupported in LOM | OFF | `tools/wav_reverse.py`, then `create_audio_clip` |
| fades, consolidate, split, freeze, flatten | Unsupported | UI / OFF | — |
| audio-to-MIDI | Missing | UI | — |

## Plugins (priority 5)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| inventory, loads (196 entries) | Working | LOM | Phase 1 bench |
| version change check (Vital 1.0.7 → 1.6.4) | Working | REC + OFF | an 808 part (Vital preset "Bass - 808 Glide") re-rendered from a copy: LUFS, peak, RMS and bands match the 1.0.7 render (−21.12 LUFS each). The null doesn't cancel, but neither do two 1.6.4 renders (per-note randomness). `tools/compare_render_window.py` |
| parameters of large plugins (Serum 2, Vital, Analog Lab V…) | Partial | ALS | only Device On until configured; the ALS tool fills the Configure list (AU tested with Vital). **Live pushes each slot's stored value into the plugin on load**: pass `@value` or set values after reopening |
| presets (`presets`, `selected_preset_index`) | Untested here | LOM | livebridge: Serum 2 and Apple AUs report only "Default" |
| snapshots, A/B parameter sets, bypass | Working | LOM | Phase 1 `snapshot_device` / `restore_device_snapshot`, `set_device_on` |

## Rendering and project (priority 6)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| render without dialogs | Working | REC + OFF | resample the Main for N bars, then `tools/audio_check.py`. The file peak equals the meter (−12.38 dBFS), which confirms the meter offset |
| audio checks: duration, rate, channels, peak, true peak, LUFS, clipping, silence, loop seam | Working | OFF | `tools/audio_check.py` (targets: exploration −18.9, combat −15.4 LUFS) |
| Save | Working | UI | File > Save Live Set (background menu) |
| Save As | Working | UI | dialog under background control |
| Export Audio, stems | Working | UI | `docs/EXPORT-PROCEDURE.md`: the dialog opens from the menu and its switches, format and Export button are reachable in the background. Render Start/Length need full-screen control (double-click the bars number exactly, type, Return; the dialog ignores the loop brace), and so does the save panel (Cmd+Shift+G). Tested: 4 bars → 8.000 s WAV, 48 kHz/24-bit, checked |
| tempo, time signature, loop brace, playhead | Working | LOM | `set_song_time`. **Playback starts from the start marker (`Song.start_time`), not the playhead**: `position=` sets both (a render cued by the playhead alone started at beat 0) |
| project sample rate | Unsupported | UI | Settings > Audio sets Live's engine rate. Match it to your project's render rate |

## Arrangement and clips (priority 7)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| Session → Arrangement copy at a bar | Working | LOM | envelopes dropped on instrument tracks |
| delete an Arrangement clip | Working | LOM | scratch-guarded |
| create a MIDI clip in the Arrangement | Working | LOM | `create_arrangement_midi_clip` (Track.create_midi_clip) |
| move, copy, trim, split Arrangement clips | Working | LOM | `tests/test_arrangement_edit.py` proves each by null test on deterministic audio: split −215.6 dB, move −45.5 dB, head trim −39 dB (Live's automatic clip-edge fade). There's no move or resize API: a move is a verified copy plus delete through a temporary spot; an unlooped clip's span is its loop_start/loop_end |
| clip fades | Unsupported | OFF / UI | not in the LOM (Live adds a short automatic edge fade); render fades offline, or draw them in the UI |
| take lanes / comping | Untested | LOM | `Track.create_take_lane`, `take_lanes` exist on 12.4.16 |
| groove, MIDI velocity / expression edits | Missing | LOM | `Clip.quantize`, note APIs exist (AbletonMCP edits notes) |

## A/B (priority 8)

| Operation | Status | Route | Evidence / limit |
|---|---|---|---|
| preserve state, alternate, render both, loudness-match, measure, restore or keep | Working | LOM + REC + OFF | `tools/ab_compare.py SPEC.json [--keep A|B]` (`tests/specs/ab_808_grit.json`): Grit 40 vs 115 rendered 8 s each, B +3.5 LUFS, +9.5 dB mid share, −3.3 dB sub share; matched copies written; original restored. Scratch sets only. Reports numbers, never a verdict |

## Write protection (0.3.0)

| Operation | Status | Evidence |
|---|---|---|
| refuse every Set-changing command until the open Set is authorized | Working | `tests/test_e2e_release.py refuse`: 20 protected commands refused, the Set unchanged, inspection still working |
| authorization bound to the Set (path + `set_id` stored in it + session key); mismatched identity refused | Working | `refuse`: a wrong `set_id` and a wrong path were both refused |
| opening another Set ends it | Working | `switched`: the control script is re-created on Set load (new session key); writes refused |
| reopening needs a fresh authorization; built material survives | Working | `reopened`: 8/8 |
| Save As to a new path ends it | Working | Live check, 2026-11-10: authorized `Release E2E`, Save As to `Release E2E SaveAs` → status not authorized; the next write was refused and the authorization revoked with the reason "the open Set changed". The control script isn't re-created by Save As and the copy keeps its stored `set_id`, so the path check is what catches it |
| classifier, fail-closed logic, validation | Working | `tests/offline/test_policy.py`: 18 tests; every command classified, unknown = write |

## Write protection 0.4.0 (WavReadBridge), tested in Live 2026-11-10

All PASS on Live 12.4.16, macOS:
- **refuse 17/17:**
  - connection, name and version; reconnection after a dropped half-request;
  - 20 protected actions refused, the Set unchanged, inspection working;
  - a direct TCP write refused;
  - a wrong set_id or path refused;
  - a request alone grants nothing and its reply carries no code;
  - a write refused while approval is pending;
  - a wrong code refused and the request ended; a confirm without a request refused;
  - an expired code refused.
- **Codes read by the owner from Live's status bar:**
  - a replaced code refused, the right code granted, a replayed code refused;
  - a code requested before a Set switch is dead after it;
  - re-approval after a reopen works.
- **write 15/15** (incl. an Apple AU plugin), **switched 2/2**, **reopened 7/7**, **reapproved 2/2**, **untitled 3/3**.
- **Transport:**
  - launching an empty slot on an armed track is refused while unauthorized;
  - with Arrangement Record on, `continue` is refused and `stop` allowed (stop is always allowed: found in Live).
- **Approval off:** turning it off needs one code (refused otherwise, tested offline). With it off, an edit in a
  never-approved Set worked; untitled Sets are still refused.
- **Found and fixed in Live:**
  - the status bar clears a control script's message after a few seconds, so the code is re-shown every second;
  - `stop` was blocked while recording.
- **Offline:** 43 tests.

## Safety rules learned in Live (all enforced in code)

- An armed **or controller-armed (implicit)** MIDI track records silence over its clips during an Arrangement
  pass. The recorder selects the Main and refuses while any track is armed.
- A gesture begun in the tick that recording starts is dropped. The recorder waits half a beat.
- Stopping Session clips detaches tracks from the Arrangement: `back_to_arrangement` first.
- `play` right after a record launch restarts the transport and cuts the recording.
- Track meters read before mute and solo, and solo overrides mute (Phase 1).
