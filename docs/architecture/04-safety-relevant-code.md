# C4 Level 4 — Safety-relevant code path

**Audience:** robotics safety reviewers, core maintainers, and incident responders
**Classification:** technical architecture

The safety-envelope gate is the most safety-relevant repository-evidence path. It evaluates mission configuration and the committed baseline; it does not call a vehicle, simulator, or actuator. The code path below reflects `hexvision.robotics.safety_envelope.SafetyEnvelopeGate`, the shared runner, the decision-log parser, and the common result model **as implemented at this revision**. The baseline-unavailable branch is intentionally shown as a recorded measurement because GAP-01/SAFE-01 remediation is owned by the safety workstream; this C4 document does not pretend that pending behavior has landed.

```mermaid
sequenceDiagram
    participant Operator as Operator / CI
    participant Runner as run_gate
    participant Gate as SafetyEnvelopeGate.evaluate
    participant Config as Config
    participant Files as Mission configuration files
    participant Git as Git baseline command
    participant Decisions as decision_ids / decision log
    participant Result as GateResult

    Operator->>Runner: execute gate with resolved Config
    Runner->>Gate: evaluate(config)
    Gate->>Config: require safety-envelope policy
    Gate->>Files: discover and parse configured mission files
    alt file or policy cannot be inspected
        Gate->>Result: blocked with finding and measurement
    else current evidence is readable
        Gate->>Git: read baseline for each mission path
        alt baseline unavailable, timeout, or malformed
            Gate->>Gate: record a baseline-status measurement
            Note over Gate,Result: Current implementation continues without a widening comparison.\nSAFE-01 remediation must change this to a non-passing result.
        else baseline is readable
            Gate->>Gate: compare each configured bound direction
            alt bound widens
                Gate->>Decisions: require configured decision authority
                alt authority is absent
                    Gate->>Result: failed finding
                else authority exists
                    Gate->>Result: reviewed result and measurements
                end
            else no widening or invalid current policy
                Gate->>Result: pass or failure findings
            end
        end
    end
    Gate-->>Runner: GateResult
    Runner-->>Operator: stable JSON/text verdict and exit code
```

Safety decisions are explicit per bound. The implementation uses the configured direction and failsafe-strength policy rather than a generic “larger is worse” rule. A failure means evidence was read and violated policy; a blocked result means the harness could not make the required inspection. Both are release-stopping and retain different incident meaning.
