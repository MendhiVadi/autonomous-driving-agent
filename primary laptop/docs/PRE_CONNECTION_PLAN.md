# Infrastructure status

The host and client implement independent reset/step transports, authenticated localhost and TLS connections, bounded controls, episode termination and diagnostic runners. Toy tests cover transport failures; the CARLA adapter supports short empty-road routes.

Remaining work includes physical two-PC validation, traffic scenarios, reward calibration, learning-framework integration, training and sustained evaluation. The primary host continues to own rendering, simulation ticks and final controls.
