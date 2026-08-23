# Decision Log — Hex-vision
Format: `YYYY-MM-DD | ID | decision | recorded-by`

Gates read this file. `G-PUB` is the final publication gate; its absence means public GitHub and Hugging Face publication tasks remain blocked. Entries are append-only and one per line. The following CONFIRM-FIRST items are OPEN, not decisions: DEC-005 safety-widening authority; DEC-006 HIL absence authorization; DEC-007 public release destination and timing; DEC-008 safety-envelope baseline source.

2026-08-22 | DEC-001 | Project name is Hex-vision. This records the kickoff naming decision only; it is not a publication or safety-widening authorization. | ian
2026-08-22 | DEC-002 | Build the Jetson/edge-AI Python pack first. This records sequencing only; it does not authorize a new stack pack or hardware operation. | ian
2026-08-22 | DEC-003 | Intended public destinations are a GitHub repository plus a Hugging Face dataset and Space. This does not authorize publication; `G-PUB` remains required. | ian
2026-08-22 | DEC-004 | Build the full project scaffold in this session. This records kickoff scope only; it does not mark any in-flight work complete. | ian
2026-08-22 | RB-001 | Re-baseline the plan because the attached archive contained no Python reference pack and no roadmap, charter, milestone, or next-steps documents. The Drive toolkit supplies the missing governance templates; the Contract v1.1 required Python-reference `remotes` Makefile and `pre-pr` changes remain implementation work. NOT a CONFIRM-FIRST gate, and it unlocks no publication or safety-bound change. | ian
2026-08-22 | DEC-009 | The upstream contract permits a valid `@governance-skip` decision annotation to authorize a pytest skip. Hex-vision deliberately diverges more strictly: every pytest skip and xfail fails, while a valid annotation is retained and named in the failure for audit evidence. This is safe and backwards compatible because it removes only a passing non-execution path and leaves the cited decision log intact. `GateStatus.SKIPPED_DECLARED` for absent hardware-in-the-loop remains unaffected: it is a failed, declared gate-capability status, not a pytest skip. | ian

<!--
DEC-010 records a control added in response to a false green observed during
development, not to an external requirement. It is logged here because the
divergence it creates is worth reviewing: the suite now refuses to run at all in
a configuration that previously ran and passed.
-->

| 2026-08-22 | DEC-010 | The test session refuses to run when the imported hexvision package resolves outside the checkout under test. A shared virtual environment holds an editable install, which is a path pointer, so a sibling clone or worktree can repoint it; the suite then passes against code that is not the code under review. This was observed in practice and produced a false green, so it is enforced at configure time rather than documented as a caveat. Cost accepted: an operator who deliberately tests an installed copy from outside its source tree must reinstall first. | architect |
