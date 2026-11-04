# Pre-connection implementation

Scope: prepare and test infrastructure only. Do not train, load old weights,
install learning frameworks, expose network ports, or delete user files.

1. Build independent, versioned JSON transports and a loopback-only gateway.
   Require an ephemeral secret, ordered requests, session identity, and a
   single-use host-issued deadline token. Invalid/stale traffic ends the session.
2. Add a dependency-free reset/step environment, requested/applied control
   reporting, bounded actions, and explicit termination/truncation reasons.
3. Add a deterministic toy backend for fast failure tests and an opt-in CARLA
   adapter for short empty-road checks. The toy backend is not CARLA evidence.
4. Add an independent client and bounded diagnostic runner with no model code.
5. Verify both apps independently and over real localhost sockets/processes;
   preserve the existing full-graphics manual launcher and legacy regressions.
6. Audit maps/downloads before transferring duplicates. Never automatically
   extract third-party packages over the existing simulator installation.

LAN/TLS, full traffic-rule scenarios, reward calibration, a learning-framework
adapter, trainer, real second-PC setup, and long evaluation runs remain later
work. The first reward contract is experimental, not training approval.
