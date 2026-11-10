# Roadmap

Planned, **not implemented**. What exists today, and how well it's tested, is in `docs/CAPABILITY-MATRIX.md`.

| Item | Notes |
|---|---|
| Export Audio and stems | Live's API has no export call. Today: resample the Main for N bars (`record_track_audio`) and check it with `tools/audio_check.py` |
| Groove editing | `Clip.quantize` and groove pool access exist in the LOM; not wrapped yet |
| MIDI velocity and expression edits | Note APIs exist; not wrapped yet |
| Windows install and testing | The code is plain Python, but nothing has been tested on Windows and there's no install script |
| Better plugin discovery | Browser search and a portable inventory that doesn't depend on one machine |
| Better automation editing | Curve tension has no effect on Live 12.4; Arrangement lanes can only be recorded, not drawn |
| Presets and effect-chain management | Save and recall chains and rack presets (rack presets can't be saved through the API) |
| Packaged installation | A pip/uvx package and an installer for the Remote Script |
| Project-state inspection | A fuller, faster snapshot of a Set |
| More MCP clients | Only Claude Code has been tested |
| Other devices' sidechains | Glue, Gate, Auto Filter and Multiband sidechain inputs are untested |
| Take lanes and comping | The LOM calls exist on 12.4; untested |
