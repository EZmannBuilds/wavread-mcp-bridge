# Tool reference

Generated from the server's registry by `tools/gen_tool_reference.py`; do not edit by hand.
`arg?` is optional. Status per feature: `docs/CAPABILITY-MATRIX.md`. Units and conventions: `docs/TOOLS.md`.

**83 tools.**

## Connection and inspection

| Tool | Arguments | What it does |
|---|---|---|
| `tooling_info` | none | Handshake: the WavReadBridge Remote Script's version, Live's version, track and return counts, whether the open set is a disposable scratch set (has a track named __TOOLING_SCRATCH__), and the command list. |
| `probe` | path?, values? | Capability detection: the attributes Live exposes on one LOM object. path: 'song', 'song.view', 'app', 'track:N' / 'return:A' / 'master' / a name, then steps 'clip:S', 'aclip:I', 'slot:S', 'device:D', 'chain:C', 'param:P', 'mixer', e.g. 'track:3/device:0/param:Frequency'. |
| `reload_extensions` | none | Re-import WavReadBridge's ext.py (Phase 2 commands) after tools/install_remote_script.sh --ext. |

## Write authorization

| Tool | Arguments | What it does |
|---|---|---|
| `get_set_identity` | none | The open Live Set's identity: file_path, name, and a set_id stored inside the Set. |
| `write_status` | none | writes_allowed (the one to check), approval mode ('code' or 'off'), whether the open Set is authorized, which Set was authorized, and why a previous authorization ended (another Set opened, Save As, reload, idle). |
| `authorize_set` | file_path, set_id | Ask the user to approve edits to the Set open right now. |
| `confirm_authorization` | code | Finish authorizing with the code the user read from Live's status bar. |
| `set_approval_mode` | mode | 'off' = no approval codes from now on (the user's choice, saved on their computer, survives restarts). |
| `revoke_authorization` | none | Make the open Set read-only again. |

## Tracks and mixer

| Tool | Arguments | What it does |
|---|---|---|
| `list_tracks` | devices? | Every track, return and the master: ref, name, kind, volume (dB as displayed), pan, mute, solo, input/output routing, monitoring, sends (dB) and device names. |
| `create_track` | kind?, index?, name? | Create an 'audio' or 'midi' track at index (-1 = end) and optionally name it. |
| `rename_track` | track, name | Rename a track or return (returns keep Live's letter prefix, e.g. 'C-Plate'). |
| `delete_track` | track | Delete a track or return. |
| `set_mixer` | track, volume_db?, pan?, mute?, solo? | Fader in dB as displayed ('-inf' allowed), pan -50 (50L) .. 50 (50R), mute, solo. |
| `set_arm` | track, arm | Arm or disarm a track; reports explicit and implicit (controller) arm. |

## Return tracks and sends

| Tool | Arguments | What it does |
|---|---|---|
| `list_return_tracks` | none | Returns (song.return_tracks): letter, name, volume dB, mute/solo, output routing, devices, and which tracks send to each one and how much. |
| `create_return_track` | name? | Add a return track at the end (song.create_return_track) and optionally name it. |
| `rename_return_track` | ret, name | Rename a return. ret: 'A', 'return:A', 'return:0' or its current name. |
| `get_return_track_devices` | ret, params? | The device chain on a return (rack chains included); params=True adds every parameter with raw and display values. |
| `load_effect_on_return_track` | ret, effect, position? | Load an effect onto a return track. effect: a native Live device's exact name ('Echo', 'Hybrid Reverb', 'EQ Eight', 'Glue Compressor') or a browser URI ('query:Plugins#VST3:MeldaProduction:MCompressor'). position: chain index (None = end). |
| `get_return_device_parameters` | ret, device | Parameters of a device on a return: index, name, raw value, min, max, display string, display_value (Hz for frequencies, ms for times), quantized items. |
| `set_return_device_parameter` | ret, device, parameter, value, units? | Set a device parameter on a return. units: 'display' (the number as Live shows it: dB, Hz, ms, %), 'raw' (internal min..max), 'auto' (strings like '800 Hz', '-6 dB', '35 %' or a quantized item name are display values; plain numbers are raw). |
| `set_return_volume` | ret, db | A return's fader in dB as displayed ('-inf' for off). |
| `inspect_return_routing` | ret | A return's output routing, its available output choices, its own sends, and the tracks feeding it. |
| `get_track_sends` | track | Every send on a track: letter, the return it feeds, raw value, display string and dB. |
| `set_track_send` | track, send, db?, value? | Set a send. send: return letter ('A'), index, or return name. db: dB as Live displays it (-inf/None = off); or value: raw knob 0..1 (only when you know why). |
| `send_curve` | track, send?, points? | Live's own raw-value -> display mapping of a send knob (for audits and docs). |

## Routing and audio buses

| Tool | Arguments | What it does |
|---|---|---|
| `get_routing` | track | A track's input/output type and channel, monitoring, and the choices Live offers right now. |
| `set_routing` | track, direction, target, channel? | Set 'output' or 'input' routing. target: a choice Live offers ('Main', 'No Output', 'Sends Only', 'Ext. |
| `set_monitoring` | track, state | Monitoring: 'in', 'auto' or 'off'. |
| `get_routing_graph` | none | Every track's routing, monitoring, mixer state and active sends, with problems found: feedback loops, double routing to Main, silent buses (monitoring off, No Output, muted, -inf), soloed buses. |
| `validate_routing` | none | Only the problems from get_routing_graph (empty list = clean). |
| `create_audio_bus` | name, sources?, volume_db?, index?, monitoring? | A real audio submix bus (not a return, not a native Group Track): a new audio track with Input 'No Input', Monitor 'In' and Output 'Main'; each source's output is then routed into it (matched by attached track). |
| `route_track_to_bus` | track, bus | Route one track's output into a bus track (reverts and errors if that would make a feedback loop). |
| `route_multiple_tracks` | tracks, bus | Route several tracks' outputs into one bus; then the routing problems. |
| `set_bus_volume` | bus, db | A bus's fader in dB as displayed. |
| `set_bus_effect_chain` | bus, chain, replace? | Load a chain onto a bus (or any track, returns included). chain: [{"effect": "Glue Compressor", "params": {"Threshold": "-18 dB"}, "units": "auto"}, "Saturator", ...] in order. replace=True first deletes the track's existing devices (scratch sets only). |

## Devices and parameters

| Tool | Arguments | What it does |
|---|---|---|
| `get_track_devices` | track, params? | A track's full device chain: index, name, class, type, on/off, plugin flag, rack chains (3 levels deep); params=True adds every parameter. |
| `load_effect` | track, effect, position? | Load an effect on any track (returns included) at a chain position. effect: native device name or browser URI. |
| `get_device_parameters` | track, device, chain?, chain_device? | Parameters of a device; chain='0' with chain_device=N reaches device N inside rack chain 0. |
| `set_device_parameter` | track, device, parameter, value, units?, chain?, chain_device? | Set one parameter by verified name or index. units as in set_return_device_parameter. |
| `set_device_parameters` | track, device, values, units?, chain?, chain_device? | Set several parameters {name: value}; every name is checked before anything is written. chain ('c' or 'c/d/c') and chain_device reach a device inside a rack (WavReadBridge 0.1.1+). |
| `set_device_on` | track, device, on? | Bypass (on=False) or enable a device through its Device On parameter. |
| `move_device` | track, device, to_position, to_track? | Reorder a device in its chain, or move it to another track (Song.move_device). |
| `delete_device` | track, device | Delete a device. |
| `snapshot_device` | track, device, save_to? | Every parameter's raw value and display string; save_to writes the snapshot as JSON to that path. |
| `restore_device_snapshot` | track, device, snapshot_path | Write a saved snapshot back (by index, only where names still match) and report what still differs. |

## Racks

| Tool | Arguments | What it does |
|---|---|---|
| `create_effect_rack` | track, name?, index?, kind? | Insert an empty rack (Audio Effect Rack, Instrument Rack, MIDI Effect Rack, Drum Rack). |
| `add_rack_chain` | track, device, name?, index? | Add a chain to a rack. |
| `insert_device_in_chain` | track, device, chain_index, name, index? | Insert a native device (exact browser name) into a rack chain. |
| `set_chain_mixer` | track, device, chain_index, volume_db?, pan?, active? | A rack chain's volume (dB), pan (-50..50) and on/off. |
| `set_rack_macros` | track, device, visible?, values?, units? | Show `visible` macros and set macro values. |

## Sidechain

| Tool | Arguments | What it does |
|---|---|---|
| `inspect_device_sidechain` | track, device, chain?, chain_device? | A device's sidechain: reachable through the LOM or not, its source, choices and S/C parameters. |
| `set_sidechain` | track, device, source, channel?, on?, params?, chain?, chain_device? | Key a device from another track (never its own), turn S/C on, set S/C or compressor parameters in display units, e.g. params={"Threshold": "-30 dB", "Ratio": "4", "Attack": "1 ms", "Release": "150 ms"}. |

## Automation

| Tool | Arguments | What it does |
|---|---|---|
| `list_automatable_parameters` | track, slot? | Every parameter a session clip on this track can automate (mixer, devices, rack chains), each with the target object to pass to the automation tools. |
| `set_automation_points` | track, slot, target, points, units?, mode?, replace? | Write breakpoints into a SESSION clip's envelope (created if needed). points: [{"at": "1.1.1", "value": v}]; mode "ramp" (lines between points) or "step" (hold until the next). |
| `set_automation_curve` | track, slot, target, shape, start, end, frm, to?, units?, curve?, resolution?, rate?, duty?, replace? | A shaped segment in a session clip: shape ramp/sweep/fade (frm -> to; curve linear, ease, exp, log), hold, pulse (to for `duty` of every `rate` beats, else frm), sine (frm..to, period `rate` beats). |
| `get_automation` | track, slot, target, start?, end?, step? | Sample a session clip's envelope every `step` beats. |
| `delete_automation` | track, slot, target? | Clear one envelope in a session clip, or all of them when target is omitted. |
| `copy_automation` | track, slot, target, to_track, to_slot, to_target?, resolution? | Copy an envelope to another session clip/parameter by sampling every `resolution` beats. |
| `validate_automation` | track, slot, target, expect, units?, tolerance? | Check expected values [{"at": pos, "value": v}] and the loop wrap (value at loop end vs loop start). |
| `record_arrangement_automation` | track, target, points, units?, preroll_bars?, wait? | ARRANGEMENT automation (the LOM can't draw it): records it in real time. |
| `param_state` | track, target | A parameter's value and automation state (0 none, 1 playing, 2 overridden). |
| `re_enable_automation` | track?, target? | Re-enable overridden automation for one parameter, or the whole song. |
| `back_to_arrangement` | none | Press Back to Arrangement (tracks follow the Arrangement and its automation again). |

## Clips, audio and recording

| Tool | Arguments | What it does |
|---|---|---|
| `get_clip` | track, slot?, arrangement_index? | A clip's markers, loop, and for audio: pitch, gain, warp mode, warp markers, file, sample rate. |
| `set_clip` | track, slot?, arrangement_index?, name?, pitch_coarse?, pitch_fine?, gain?, warping?, warp_mode?, looping?, loop_start?, loop_end?, start_marker?, end_marker? | Clip properties; positions musical. warp_mode 0 beats, 1 tones, 2 texture, 3 re-pitch, 4 complex, 6 complex pro. gain 0..1 (0.4 = 0 dB). |
| `warp_marker` | track, action, beat, slot?, arrangement_index?, seconds?, delta? | Add (beat + seconds), move (beat, delta beats) or remove (beat) a warp marker on an audio clip. |
| `create_audio_clip` | track, path, slot?, at? | Load an audio file (absolute path) into a session slot or the Arrangement at a position (audio tracks). |
| `make_test_clip` | track, slot?, length?, notes?, name?, fire? | A looping session MIDI clip for tests: notes [[pitch, start_beats, length_beats, velocity], ...]. |
| `fire_clip` | track, slot? | Launch a session clip slot. |
| `duplicate_to_arrangement` | track, slot, at | Copy a session clip into the Arrangement. |
| `record_track_audio` | dst, source, slot?, bars?, channel?, wait? | Record (resample) a track's output, or "Resampling" for the Main, into a session slot of an audio track for exactly `bars` bars. |

## Arrangement editing

| Tool | Arguments | What it does |
|---|---|---|
| `list_arrangement_clips` | track | A track's Arrangement clips: index, name, start and end (beats), looping, audio. |
| `move_arrangement_clip` | track, to, at?, index?, to_track? | Move an Arrangement clip (found by its start `at` or `index`) to a musical position, optionally on another track of the same kind. |
| `copy_arrangement_clip` | track, to, at?, index?, to_track? | Copy an Arrangement clip to a musical position (pastes over whatever is there). |
| `trim_arrangement_clip` | track, at?, index?, start?, end? | Trim an Arrangement clip to [start, end) in song time, content kept in place (clip unlooped). |
| `split_arrangement_clip` | track, split_at, at?, index? | Split an Arrangement clip at a song position into two clips that play exactly as before (null -215 dB). |
| `create_arrangement_midi_clip` | track, at, length, notes?, name? | A MIDI clip directly in the Arrangement; notes [[pitch, start, length, velocity]] in clip beats. |

## Transport, time and metering

| Tool | Arguments | What it does |
|---|---|---|
| `transport` | action, time_beats? | 'play' (from time_beats if given), 'continue', 'stop', 'stop_all_clips'. |
| `set_song_time` | tempo?, numerator?, denominator?, loop?, loop_start?, loop_length?, position? | Tempo, time signature, loop brace, and the playhead position (set it while stopped). |
| `measure_levels` | tracks?, seconds?, interval? | Poll output meters while Live plays and report each track's peak dBFS over the window (meter dBFS = 76 * raw - 70, verified in docs/UNITS.md; None = below -70 dBFS, i.e. silent). |
| `capture` | tracks, seconds?, params? | Sample meters (dBFS) and optional parameters [{"track", "target"}] inside Live at ~10 Hz, stamped with song time, for `seconds` while Live plays. |
