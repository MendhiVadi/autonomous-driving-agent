# Next steps

1. On laptop 2, receive and verify the updated package and open the local vault.
2. Inventory laptop 2 hardware and Python availability.
3. Validate the physical TLS gateway connection on Town02_Opt with brake-held steps.
4. Measure round-trip time, rendered performance and disconnect/recovery behavior.
5. Coordinate stable Ethernet addresses if needed.
6. Implement missing traffic observations, rewards, evaluation scenarios and framework wrappers.
7. Choose learning dependencies from laptop 2's hardware; implement trainer,
   checkpoints and inference adapter from scratch.
8. Evaluate learned behavior separately from safety interventions.

Keep model training off during connection diagnostics. Record measured results in
[[Session-Log]] and update [[Architecture]] and [[Data-Contract]] when code changes.

Legacy cockpit follow-ups (one-laptop system; details in [[Three-Camera-Neural-Driving-Handoff]]):
confirm real keyboard focus by hand, then decide how to treat Town13 sharp corners and the
start-assist speed cap. These do not block the two-laptop connection work above.
