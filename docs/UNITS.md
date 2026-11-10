# Units, measured on this Mac (Live 12.4.16, 2026-11-10)

All numbers below were measured in the scratch set (`Tooling Scratch Project/Tooling Scratch Saved.als`) by
`tests/test_returns.py` and `tests/test_buses.py`. Results: `tests/results/returns-*.json`, `tests/results/buses.json`.

## Sends: three scales for one knob

| Displayed in Live | LOM `send.value` (knob position) | `.als` `TrackSendHolder/Send/Manual` (linear gain) |
|---|---|---|
| 0 dB (the maximum) | 1.0 | 1.0 |
| -6 dB | 0.85 | 0.5011872 |
| -12 dB | 0.70 | 0.2511887 |
| -20 dB | 0.50 | 0.1000000 |
| -24 dB | 0.40 | 0.0630957 |
| off (-inf) | 0.0 | 0.0003162 (-70 dB, Live's floor) |

- **LOM**: for knob values 0.4 to 1.0, `dB = 40 * v - 40` exactly. Below 0.4 the curve bends
  (0.3 = -30.2 dB, 0.2 = -40.4 dB, 0.1 = -54.6 dB, 0.025 = -67.6 dB). The full 41-point table is in
  `tests/results/returns-build.json` (step "6 send curve recorded"). Never compute it: write in dB with
  `set_track_send(db=...)`, which uses `display_value` and reads it back.
- **`.als`**: `Manual` is linear amplitude, `10 ** (dB / 20)`. Writes of
  0.25 / 0.1 / 0.5 read back through the LOM as 0.699 / 0.5 / 0.849, which are -12 / -20 / -6 dB on the knob.
- **Audible check**: with the return's Echo bypassed, return peak minus source peak measured -6.00, -12.00 and
  -20.00 dB, before and after a save and reopen.

## Track and return faders

- LOM `mixer_device.volume.value` 0.85 = 0 dB (the fader goes to +6 dB). Write in dB with `set_mixer(volume_db=)`.
- A -12 dB fader move measured exactly -12.00 dB on the meter (the bus test).

## Meters

- `dBFS = 76 * output_meter_level - 70` (elleural's figure). The **slope** is confirmed here: the -12 and -20 dB sends and
  the -12 dB fader all measured to within 0.01 dB. The absolute offset isn't checked against an external meter yet.
- **A track's own output meter reads before its mute and its solo state.** A muted return or bus still meters its
  input. Judge a mute by what reaches the main or the bus it feeds, never by the muted track's own meter.
- Meters hold peaks about 1 s. Wait 2 s after a change before measuring.

## Mute, solo and routing behaviour

- Sends are **post-fader** by default: a source at -70 dB sends nothing.
- **Solo overrides mute**: a soloed and muted return still plays.
- Muting a return, or a bus, drops the main by the same amount as pulling its fader to -inf (measured: return
  -2.88 → -3.87 dBFS main, bus -2.88 → -8.28 dBFS main).
- Soloing a track that feeds a bus keeps that bus audible and carries only that track (solo-in-place follows routing).
- Live itself refuses a feedback route: a bus's output choices leave out the tracks that feed it.
- Routing lists fill on the next tick after a track is created (the tools retry for about 1.5 s).

## Saving

- The LOM has no save. Use the File menu (Save Live Set). A set made from the old default template forces Save As;
  the scratch set was saved as `Tooling Scratch Saved.als` in its project folder.
