# C4 architecture set

**Audience:** maintainers, pack authors, release engineers, and security reviewers
**Classification:** technical architecture

This set records Hex-vision using the four C4 levels. It is a complement to the interface and configuration detail in [the architecture guide](../ARCHITECTURE.md), not a second specification. The diagrams use Mermaid and describe only the components present in `src/hexvision` at this revision.

1. [Level 1 — system context](01-system-context.md)
2. [Level 2 — containers](02-containers.md)
3. [Level 3 — components](03-components.md)
4. [Level 4 — safety-relevant code path](04-safety-relevant-code.md)

The important boundary throughout is that Hex-vision evaluates repository evidence and recorded governance authority. It does not control a vehicle, actuator, simulator, or hardware runner.
