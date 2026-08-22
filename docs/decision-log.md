# Decision Log — Hex-vision
Format: `YYYY-MM-DD | ID | decision | recorded-by`

Gates read this file. `G-PUB` is the final publication gate; its absence means public GitHub and Hugging Face publication tasks remain blocked. Entries are append-only and one per line. The following CONFIRM-FIRST items are OPEN, not decisions: DEC-005 safety-widening authority; DEC-006 HIL absence authorization; DEC-007 public release destination and timing; DEC-008 safety-envelope baseline source.

2026-08-22 | DEC-001 | Project name is Hex-vision. This records the kickoff naming decision only; it is not a publication or safety-widening authorization. | ian
2026-08-22 | DEC-002 | Build the Jetson/edge-AI Python pack first. This records sequencing only; it does not authorize a new stack pack or hardware operation. | ian
2026-08-22 | DEC-003 | Intended public destinations are a GitHub repository plus a Hugging Face dataset and Space. This does not authorize publication; `G-PUB` remains required. | ian
2026-08-22 | DEC-004 | Build the full project scaffold in this session. This records kickoff scope only; it does not mark any in-flight work complete. | ian
2026-08-22 | RB-001 | Re-baseline the plan because the attached archive contained no Python reference pack and no roadmap, charter, milestone, or next-steps documents. The Drive toolkit supplies the missing governance templates; the Contract v1.1 required Python-reference `remotes` Makefile and `pre-pr` changes remain implementation work. NOT a CONFIRM-FIRST gate, and it unlocks no publication or safety-bound change. | ian
