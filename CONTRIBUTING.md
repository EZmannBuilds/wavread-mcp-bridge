# Contributing

Thanks for helping. Two rules matter more than any other here: **a tool never claims success it hasn't read back**, and
**nothing changes a Live Set unless that Set has been authorized for writing** (see the README's Safety section).

## Set up

- Clone, then run the offline suite (no Live needed):
  ```bash
  uv run --with "mcp[cli]>=1.9,<2" --with numpy --with soundfile --with pyloudnorm --with scipy --with pytest pytest tests/offline
  ```
- To work against Live, install the Remote Script (`tools/install_remote_script.sh`), restart Live, and enable it as a
  Control Surface. Changes to `ext.py` hot-reload: `tools/install_remote_script.sh --ext`, then call `reload_extensions`.
  Changes to `__init__.py` need a Live restart.

## Adding a tool

1. Add the command to the Remote Script (`ext.py` for most new work). Run every Live Object Model call on Live's main
   thread, the way the existing commands do.
2. Classify it in the write policy as read or write. Unknown commands are treated as writes.
3. Add the MCP wrapper in `server/ableton_tooling_server.py` with a docstring that states units and limits.
4. Add it to a group in `tools/gen_tool_reference.py` and regenerate `docs/TOOL-REFERENCE.md`.
5. Prove it in Live on a disposable Set (a `tests/test_*.py` script), and record the result in `docs/CAPABILITY-MATRIX.md`
   as Working, Partial or Untested. Don't mark anything Working that you haven't read back, reopened and, where it
   applies, heard.

## Pull requests

- Keep the offline suite green; CI runs it.
- Don't commit Live Sets, audio you don't own, plugin binaries, or lists of your installed paid plugins.
- Tests must not depend on paid third-party plugins. Live's own devices, the Core Library and free plugins are fine.
