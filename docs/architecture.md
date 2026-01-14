# Architecture (Early Notes)

Starstream Core is an open framework for **simulation + baseline control** of hybrid
optical–electronic integration layers.

## Near-term goals (v0.x)

- Define minimal resource abstractions (optical channels/wavelengths, compute targets)
- Provide baseline schedulers and policy scaffolds
- Add a tiny simulation harness to evaluate decisions under synthetic load/faults

## Non-goals (for now)

- Production control plane
- Vendor-specific drivers / SDK integrations
- Hardware implementations

## Core idea

Expose *control* (actuation) and *monitoring* (telemetry) endpoints at the integration
layer so higher-level software—Python logic and accelerator-oriented programming models—
can reason about optical bandwidth resources in a unified way.
