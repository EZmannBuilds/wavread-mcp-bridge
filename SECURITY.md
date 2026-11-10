# Security

## Scope of control

While the Remote Script is loaded, any process on your computer that can open a TCP connection to `127.0.0.1:9878`
can drive Live through it. It binds to loopback only and never listens on other interfaces. There is no
authentication between local processes, so unload the Control Surface when you aren't using it, and don't forward the
port.

Write operations are refused unless the currently open Set has been authorized for writing (README, Safety). That
protects your Sets from mistakes; it is not a defence against malicious software already running on your machine.

## Reporting

Please report vulnerabilities privately through GitHub's
[security advisories](https://github.com/EZmannBuilds/wavread-mcp-bridge/security/advisories/new), not in a public
issue. Include the Live version, OS, Remote Script version and the steps to reproduce.
