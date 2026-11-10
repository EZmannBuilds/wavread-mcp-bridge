# How other Live 12 integrations reach each Phase 2 operation (read 2026-11-10)

Read-only study of three MIT-licensed projects, none of them tested on our Live 12.4.16:
- livebridge (valentijnh/livebridge-ableton-mcp): head 2026-09-23, tested on Live 12.4.5.
- elleural/ableton-mcp: head 2026-10-08, `docs/spikes.md` on Live 12.4.6.
- windmonarch/AbletonMCP: head 2026-10-27.

No code is copied. Each technique is re-tested on this Mac before a command relies on it (the capability matrix
records the result). Claims the repos disagree on are flagged.

## Session clip automation (supported by the LOM)
- `clip.automation_envelope(param)` or `clip.create_automation_envelope(param)`; `clip.clear_envelope(param)`.
- Steps: `envelope.insert_step(start_beats, length_beats, value)`. It writes two breakpoints per border, and
  `value_at_time` exactly on a border returns the value before it, so read at t + 1e-4.
- True ramps: `envelope.delete_events_in_range(a, b)` then `envelope.create_event(Live.Envelope.EnvelopeEvent(t, v))`.
  Two events at the same time make a step. `delete_events_in_range` is inclusive, with a ±1576800-beat limit.
- Time is clip-local beats. Values are in the parameter's min..max range. `EnvelopeEvent.value` can read back in
  other units, so verify with `value_at_time`. `control_coefficients` (curves) has no effect.
- An envelope always follows the clip's loop. An "unlinked" envelope length isn't in the LOM.
- Only parameters on the clip's own track. Mixer: `mixer_device.volume`, `.panning`, `.sends[i]`, `.track_activator`.

## Arrangement automation (restricted)
- Track-level arrangement lanes can't be drawn. Arrangement clips refuse `create_automation_envelope`. Envelopes
  that arrive with a copy are listed in `clip.automation_envelopes` and can be edited.
- **Disputed:** whether envelopes survive `duplicate_clip_to_arrangement`. elleural says yes; livebridge measured that
  they are all dropped once the track holds an instrument. Test it here.
- Real-time recording (livebridge, real Live only for its refusal paths):
  1. Set `song.session_automation_record = True`, loop and punch off.
  2. On the next tick, set `song.record_mode = True`.
  3. While playing: `param.begin_gesture()`, `param.value = v` every ~100 ms, then `param.end_gesture()`.
  4. Stop, and restore the saved state.
- `param.automation_state` (0 none, 1 playing, 2 overridden), `param.re_enable_automation()`,
  `song.re_enable_automation()`.
- Next-tick properties: `record_mode`, `punch_*`, `session_automation_record`, `loop`, `is_playing`,
  `current_song_time`. `back_to_arranger` can only be set to False.

## Sidechain
- On a device with `available_input_routing_types`, set `input_routing_type` / `input_routing_channel`, then set
  "S/C On" to its maximum. On 12.4.5 only Compressor (`Compressor2`) exposes a sidechain source. Glue Compressor,
  Gate, Auto Filter and Multiband have S/C parameters but no routing (verify on 12.4.16).
- Compressor's S/C parameters: S/C On, S/C Listen, S/C Gain, S/C Mix, S/C EQ On/Type/Freq/Q/Gain.

## Racks
- `Track.insert_device("Audio Effect Rack", i)` (12.3+); `rack.insert_chain(i)` returns the Chain;
  `chain.insert_device(name, -1)`; `Song.move_device(device, chain, i)`.
- Chain mixer: `chain.mixer_device.volume/panning/chain_activator`.
- Macros: `visible_macro_count`, `add_macro()` / `remove_macro()` (in steps of 2), `store_variation` and recall.
- **Macro → parameter mapping is impossible through the LOM.** livebridge writes `.adg` rack-preset XML with
  `MacroControlIndex` and loads it through the browser:
  - more than 128 plug-in parameters, or an empty `<MidiControllerRange/>`, crashes Live;
  - AU plug-ins expose nothing in such racks.
- Not in the LOM: delete, duplicate or reorder chains; rack zones; saving presets.

## Recording and resampling
- `track.arm = True` (ignores Exclusive Arm). Input routing "Resampling" or another track, with channel
  Pre FX / Post FX / Post Mixer, set a tick after the track is created.
- Session recording: `clip_slot.fire(record_length=...)`. **Disputed:** elleural says `fire()` takes no arguments on
  12.4.6.
- Arrangement: `song.record_mode = True`. livebridge resamples through loop brace and punch in/out (measured exact on
  12.4.5).
- `song.capture_midi()`. From files: `ClipSlot.create_audio_clip(abs_path)` and
  `Track.create_audio_clip(path, beats)` (audio tracks only; they paste over existing clips and move the playhead).

## Audio clip editing
- In the LOM:
  - `pitch_coarse`, `pitch_fine` (fine carries into coarse at ±50); `gain` (0.4 = 0 dB);
  - `warping`, `warp_mode` (0 beats, 1 tones, 2 texture, 3 re-pitch, 4 complex, 6 complex pro; check
    `available_warp_modes`);
  - warp markers through `add_warp_marker(Live.Clip.WarpMarker(...))`, `move_warp_marker`, `remove_warp_marker`;
  - start and end markers, loop, `crop()`, `duplicate_loop()`.
- Not in the LOM: fades, reverse (only Simpler's reverse, which writes a new file), consolidate, split, freeze,
  flatten.

## Plug-ins
- `presets` / `selected_preset_index`: Serum 2 and Apple AUs report only "Default".
- `parameters` holds Device On plus the Configure list. Large plug-ins expose none of their own, and no API adds them.
  `get_parameter_names()` lists them all.
- Workaround: a generated VST3 rack preset with up to 128 parameters. AU plug-ins expose nothing that way.

## Save, export, project
- The LOM can't save, export, freeze, set the project sample rate, group tracks, or edit time-signature markers. Use
  UI automation: Cmd+S, Cmd+Shift+S, Cmd+Shift+R plus the export dialog, `open -a`. Loading a set re-creates the
  control surface.
- `signature_numerator/denominator`, `loop`, `loop_start`, `loop_length`. Song-length wall: positions past
  max(material end, loop end) + 32 beats raise.
- Deleting several tracks in one main-thread tick crashed Live once (elleural): delete one object per call.
