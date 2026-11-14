# Third-party notices

This project contains no code copied from the projects below. Its Remote Script and MCP server are written
independently. They use the same JSON-over-TCP request shape as AbletonMCP, so the two can run side by side, and a
few techniques were learned by reading these MIT-licensed projects (each one re-tested in Live before use, see
`docs/REFERENCE-LOM-TECHNIQUES.md`). Credit and license texts:

| Project | License | Copyright | What we took |
|---|---|---|---|
| [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) | MIT | (c) 2025 Siddharth Ahuja | The request/response shape (`{"type", "params"}` → `{"status", "result" or "message"}`) and the companion design: this server runs beside it on another port |
| [elleural/ableton-mcp](https://github.com/elleural/ableton-mcp) | MIT | (c) 2025 Siddharth Ahuja | Techniques: writing `display_value` with a `str_for_value` bisection fallback, resolving routing against Live's available routing lists, the meter-to-dBFS mapping |
| [windmonarch/AbletonMCP](https://github.com/windmonarch/AbletonMCP) | MIT | (c) 2026 windmonarch | Read as a reference for return-track and send commands |
| [valentijnh/livebridge-ableton-mcp](https://github.com/valentijnh/livebridge-ableton-mcp) | MIT | (c) 2026 Valentijn | Read as a reference for automation and sidechain behaviour on Live 12.4 |

Runtime dependencies (installed by the user, not bundled): the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
(MIT), and for the offline audio tools numpy, scipy (BSD-3-Clause), soundfile (BSD-3-Clause) and pyloudnorm (MIT).

Ableton, Live and Push are trademarks of Ableton AG. Faderhand is an independent project and is not
affiliated, associated, authorized, endorsed by, or in any way officially connected with Ableton AG.
The Remote Script uses Live's `_Framework` and Live Object Model, which ship with Live and are not included here.
Plugin names mentioned in docs and tests (Vital, MeldaProduction, Serum, Arturia and others) belong to their owners.
