# Two-device autonomous-driving architecture

```mermaid
flowchart LR
    subgraph Device1[Device 1: simulation and visual console]
        S[CARLA server]
        T[Traffic, weather, maps, potholes]
        C[Dedicated rigid front and rear cameras]
        M[Dedicated rigid left and right cameras]
        S --> T
        S --> C
        S --> M
    end

    subgraph Device2[Device 2: neural-network workload]
        R[Sensor and state receiver]
        N[Inference-only neural baseline]
        G[Overhead map and network visualization]
        P[Safety and control policy]
        R --> N --> P
        R --> G
    end

    C -->|Ethernet: sensor stream| R
    M -->|Ethernet: sensor stream| R
    P -->|Ethernet: control commands| S
```

Device 1 remains responsible for simulation truth and rendering. Device 2
performs inference and can display the overhead map. Training remains disabled
until a reviewed dataset and evaluation plan are available. The safety layer
must remain active even when the neural network is remote.
