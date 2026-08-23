---
language:
- en
license: apache-2.0
tags:
- governance
- robotics
- edge-ai
- traceability
- software-quality
pretty_name: Hex-vision governance evidence
size_categories:
- n<1K
---

# Hex-vision governance evidence

## Dataset summary

This card describes the structured governance evidence produced by Hex-vision, a Gate Harness Contract v1.1 implementation for drone, robotics, and edge-AI repositories. The harness emits evidence about repository controls; it does not contain vehicle-control data, sensor recordings, or an airworthiness decision.

The evidence is intended for repository review, CI artefacts, and audit narratives. A result must retain the distinction between a policy failure and an unavailable control: `failed` means the check inspected evidence and found a violation, while `blocked` means it could not inspect required evidence, policy, or tooling.

## Evidence artefacts and schemas

### Gate and conformance results

CLI gate commands with `--json`, including `hexvision conformance --pack jetson --json`, emit one JSON object with this shape:

```json
{
  "gate": "string",
  "status": "passed | failed | blocked | skipped-declared",
  "clause": "string or null",
  "summary": "string",
  "exit_code": 0,
  "findings": [
    {
      "id": "string",
      "severity": "Blocker | Major | Minor | Info",
      "message": "string",
      "location": "string or null",
      "clause": "string or null",
      "disposition": "string or null",
      "context": {}
    }
  ],
  "measurements": {}
}
```

`exit_code` is 0 for `passed`, 1 for `failed` and `skipped-declared`, and 2 for `blocked`; CLI invocation errors use 3. `measurements` preserves gate-specific values, such as latency headroom, model counts, or runtime observations. Findings are ordered by severity and stable ID so repeated results remain diffable.

Conformance uses the same result envelope. Its measurements include the target count, domain-gate count, and declared invariant-enforcement mapping. Its invariant verifier evidence proves a negative probe detected the declared mechanism rather than treating configuration as sufficient proof.

### Requirement traceability matrix

`traceability/REQUIREMENT-TRACEABILITY.md` is a checked Markdown projection of the OpenSpec requirement set. Its schema is one row per requirement with these columns:

| Column | Meaning |
| --- | --- |
| `requirement id` | Source requirement identifier, such as `R-11`. |
| `statement` | Requirement statement. |
| `status` | Configured evidence status. |
| `test node id` | Pytest node or nodes supporting the status. |
| `inherits-from` | Required inheritance detail for an `Inherited` row. |
| `decision ref` | Required decision-log reference for a `Waived` row. |
| `notes` | Human-readable evidence context. |

The traceability gate derives requirements and scenarios from `openspec/changes/add-robotics-governance-harness/specs/`, validates the configured status vocabulary, and requires every Green test node to collect and to contain the corresponding executable traceability marker.

### Decision log

`docs/decision-log.md` is an append-only authority record. Its configured row schema is:

```text
YYYY-MM-DD | ID | decision | recorded-by
```

Only rows that satisfy the configured grammar count as authority; examples in code fences and HTML comments do not. The log records decisions that gates rely on, including publication authority. A `G-PUB` row is required by the R-17 publication control in addition to destination allowlisting.

## Data fields and privacy

Evidence can name repository-relative paths, configured destinations, tool outcomes, measured gate values, and decision identifiers. Do not put secrets, private credentials, or sensitive operational data in model cards, gate measurements, findings, or decision records. The secret gate covers working tree and Git history, but repository authors remain responsible for reviewing what they publish.

## Use and limitations

Use this evidence to inspect whether declared repository controls were evaluated and what they found. Do not interpret a passing result as a flight-safety guarantee, an airworthiness approval, a statement that hardware was commanded, or an authorisation to publish. A declared HIL absence is visible non-passing evidence unless authorised by the relevant gate policy.

## Licence

The harness and this evidence schema are published under Apache License 2.0. See [LICENSE](LICENSE).
