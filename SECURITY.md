# Security

## Scope of control

While the Remote Script is loaded, any process on your computer that can open a TCP connection to `127.0.0.1:9878`
can drive Live through it. It binds to loopback only and never listens on other interfaces. There is no
authentication between local processes, so unload the Control Surface when you aren't using it, and don't forward the
port.

There is no approval step (since 0.5.0): tools edit whichever saved Set is open. The guards that remain refuse
unsaved Sets and allow deletions only in a disposable Set (README, Safety). They protect against mistakes, not against
malicious software already running on your machine. Work on copies of Sets that matter.

## Reporting

Please report vulnerabilities privately through GitHub's
[security advisories](https://github.com/EZmannBuilds/wavread-mcp-bridge/security/advisories/new), not in a public
issue. Include the Live version, OS, Remote Script version and the steps to reproduce.
