# Decision Log — Hex-vision
Format: `YYYY-MM-DD | ID | decision | recorded-by | subject | status | supersedes`

Gates read this file. `G-PUB` is the final publication gate; its absence means public GitHub and Hugging Face publication tasks remain blocked. Entries are append-only and one per line. The following CONFIRM-FIRST items are OPEN, not decisions: DEC-005 safety-widening authority; DEC-006 HIL absence authorization; DEC-007 public release destination and timing; DEC-008 safety-envelope baseline source.

`subject`, `status`, and `supersedes` were added by DEC-018. `subject` is optional: a blank or placeholder cell (`-`) authorizes nothing. `status` is required and must read `active` to be authoritative; any other value, or its absence, is non-authoritative. `supersedes` is optional and append-only: a later record naming an earlier id there makes that earlier record non-authoritative regardless of the earlier record's own `status` cell, because no historical row's cells are edited after the one-time migration that introduced these columns. Superseding with the same conclusion (a reconfirmation) and superseding with a different conclusion (a withdrawal) use the same mechanism; only the prose differs.

2026-08-22 | DEC-001 | Project name is Hex-vision. This records the kickoff naming decision only; it is not a publication or safety-widening authorization. | ian | - | active | -
2026-08-22 | DEC-002 | Build the Jetson/edge-AI Python pack first. This records sequencing only; it does not authorize a new stack pack or hardware operation. | ian | - | active | -
2026-08-22 | DEC-003 | Intended public destinations are a GitHub repository plus a Hugging Face dataset and Space. This does not authorize publication; `G-PUB` remains required. | ian | - | active | -
2026-08-22 | DEC-004 | Build the full project scaffold in this session. This records kickoff scope only; it does not mark any in-flight work complete. | ian | - | active | -
2026-08-22 | RB-001 | Re-baseline the plan because the attached archive contained no Python reference pack and no roadmap, charter, milestone, or next-steps documents. The Drive toolkit supplies the missing governance templates; the Contract v1.1 required Python-reference `remotes` Makefile and `pre-pr` changes remain implementation work. NOT a CONFIRM-FIRST gate, and it unlocks no publication or safety-bound change. | ian | - | active | -
2026-08-22 | DEC-009 | The upstream contract permits a valid `@governance-skip` decision annotation to authorize a pytest skip. Hex-vision deliberately diverges more strictly: every pytest skip and xfail fails, while a valid annotation is retained and named in the failure for audit evidence. This is safe and backwards compatible because it removes only a passing non-execution path and leaves the cited decision log intact. `GateStatus.SKIPPED_DECLARED` for absent hardware-in-the-loop remains unaffected: it is a failed, declared gate-capability status, not a pytest skip. | ian | - | active | -

<!--
DEC-010 records a control added in response to a false green observed during
development, not to an external requirement. It is logged here because the
divergence it creates is worth reviewing: the suite now refuses to run at all in
a configuration that previously ran and passed.
-->

| 2026-08-22 | DEC-010 | The test session refuses to run when the imported hexvision package resolves outside the checkout under test. A shared virtual environment holds an editable install, which is a path pointer, so a sibling clone or worktree can repoint it; the suite then passes against code that is not the code under review. This was observed in practice and produced a false green, so it is enforced at configure time rather than documented as a caveat. Cost accepted: an operator who deliberately tests an installed copy from outside its source tree must reinstall first. | architect | - | active | - |
| 2026-08-22 | DEC-011 | A mission baseline comparison is valid only when the configured command reads and parses the prior mission. A non-new-mission command failure, timeout, unavailable runner, malformed baseline, or unsafe evidence path returns BLOCKED with bounded redacted diagnostics; it cannot be represented as a clean new mission. A genuinely absent baseline follows the explicit frozen `new_mission_requires_decision` policy. | safety-evidence | - | active | - |
| 2026-08-22 | DEC-012 | Password-bearing remote userinfo and absent hardware-in-the-loop runners remain unconditional policies. Their misleading configuration toggles were removed because neither safe behavior has a reviewed insecure alternative: credential-bearing URLs are always rejected, and missing hardware evidence always requires an explicit decision. Jetson launcher construction remains Makefile authority; unused pack launcher keys were removed rather than implying overlays control Make. | architect | - | active | - |

<!--
DEC-013 and DEC-014 authorise the absence of hardware-in-the-loop runners in this
environment. They are recorded separately, one per runner, because the gate
resolves authority per runner: a single blanket entry would let a later runner be
added and silently inherit an authorisation nobody granted it.

Both are reconfirmed under the widened schema by DEC-019 and DEC-020 below,
which supersede them: DEC-013/DEC-014's text is retained verbatim for audit
history, but the superseding entries are authoritative for
`verify_authority` going forward.
-->

| 2026-08-22 | DEC-013 | The hil_smoke hardware runner is unavailable in this environment. No drone or Jetson hardware is attached to the development and CI environment, so the smoke scenario cannot execute and its evidence cannot be produced. The absence is accepted for pre-release validation only. It is not accepted for a flight-authorising release: the release checklist in docs/NEXT-STEPS.md carries provisioning real hardware evidence as outstanding work, and this entry must be withdrawn rather than extended once a rig exists. | architect | hardware-in-loop:hil_smoke | active | - |
| 2026-08-22 | DEC-014 | The sitl_mission hardware runner is unavailable in this environment. Software-in-the-loop mission simulation is not provisioned here, so the gate cannot observe mission execution. Accepted on the same terms as DEC-013 and withdrawn on the same trigger. Recording this separately from DEC-013 keeps per-runner authority explicit, so adding a third runner blocks until someone accepts it by name. | architect | hardware-in-loop:sitl_mission | active | - |

<!--
DEC-015 settles a contradiction found during the third review pass, where two
parts of the codebase encoded opposite answers to the same question.
-->

| 2026-08-22 | DEC-015 | An authorised declared skip passes the release aggregate; an unauthorised one does not. Two parts of the codebase disagreed: the status mapping documented that the authorising decision-log entry converts a declared skip to a pass, while the release aggregate returned a red exit for every declared skip regardless of authority. The mapping wins, because the alternative makes the decision log decorative: no release could ever go green while a documented and owned exception existed, so the incentive would be to delete the skip rather than record it. Visibility is preserved separately rather than through the exit code: the aggregate counts declared skips in its summary and lists each one against the decision that authorises it. Absences with no authority are reported BLOCKED by the producing gate, so they cannot reach this path unnoticed. | architect | - | active | - |

<!--
DEC-016 records a deliberate stop. The three findings behind it are instances
of one root cause, and the response to a third recurrence is a design change,
not a third round of point fixes.
-->

| 2026-08-22 | DEC-016 | Release is not authorised, and the three open authority findings will not be point-patched. Three independent sites accept authority without verifying it: release aggregation treats any non-empty decision_id string as authorisation, hardware-in-loop matches a runner name as a substring of the entire joined record so an unrelated subject or a withdrawn record authorises a skip, and agent validation passes with zero discovered definitions. This is the third review cycle in which the same class has appeared at new sites after being fixed at old ones, which identifies the root cause as architectural rather than local: authority checking is re-implemented per site, and each re-implementation is wrong differently. The corrective action is a single authority verifier that returns typed verified-authority values which a gate cannot construct itself, an authority record schema carrying explicit machine-readable subject and lifecycle fields, and aggregation that accepts only that type. Point-fixing the three known sites would leave the mechanism that produced them intact. | architect | - | active | - |

<!--
DEC-017 resolves a peer-review finding raised while planning DEC-016's
remediation: the repository was already public on GitHub with real pushed
history, and no G-PUB entry existed, which the review flagged as a possible
C-6 breach. This entry is the repository owner's disposition of that finding,
given directly in the planning conversation for the Order 0-6 remediation
backlog.
-->

2026-08-23 | DEC-017 | Clarification of C-6 scope. "Publication" as gated by the required `G-PUB` entry refers to a formal tagged release and the Hugging Face dataset/Space destinations named in DEC-003, not to ordinary development pushes to the already-established GitHub origin (`ianshank/Hex-vision`). This repository has been public on GitHub with real commit history since project kickoff; that state is not itself a publication event under C-6 and required no separate G-PUB entry. This clarification does not authorize the Hugging Face destinations or any additional public surface — those remain gated by G-PUB and the still-open DEC-007 proposal in charter/CHARTER.md §5. | ian | - | active | -

<!--
DEC-018 authorizes the schema migration performed in this same change, which
widens every record in this file -- including DEC-001 through DEC-017 above,
and DEC-018 itself -- from 4 columns to 7. The first four cells of every
pre-existing record are preserved byte-for-byte; this was mechanically
verified before merge, not only reviewed by eye.
-->

2026-08-23 | DEC-018 | Authorizes widening the decision-log record schema from 4 columns (date, id, decision, recorded-by) to 7 (date, id, decision, recorded-by, subject, status, supersedes), per DEC-016's mandate for a single authority verifier backed by "an authority record schema carrying explicit machine-readable subject and lifecycle fields." All 13 pre-existing records are migrated to the new column count in this same change; their first four cells are preserved byte-for-byte, mechanically verified before merge. `subject` is optional (a blank or placeholder cell authorizes nothing); `status` is required and must read `active` to be authoritative; `supersedes` is optional and append-only — a later record naming an earlier id there makes that earlier record non-authoritative regardless of the earlier record's own status cell, since no historical row's cells are edited after this one-time migration. | ian | - | active | -

<!--
DEC-019 and DEC-020 reconfirm DEC-013 and DEC-014 under the widened schema,
using the same append-only supersession mechanism a future withdrawal will
use: superseding with the same conclusion (a reconfirmation) and superseding
with a different conclusion (a withdrawal) are structurally identical here,
only the prose differs.
-->

2026-08-23 | DEC-019 | Reconfirms DEC-013 under the widened schema. The hil_smoke hardware runner remains unavailable in this environment; no drone or Jetson hardware is attached to the development and CI environment as of this entry's date. This record supersedes DEC-013: DEC-013's original text is retained verbatim for audit history but is no longer the active authority for the `hardware-in-loop:hil_smoke` subject. The absence remains accepted for pre-release validation only, on the same terms DEC-013 originally stated, and must itself be superseded rather than extended once a rig exists. | architect | hardware-in-loop:hil_smoke | active | DEC-013
2026-08-23 | DEC-020 | Reconfirms DEC-014 under the widened schema. The sitl_mission hardware runner remains unavailable in this environment; software-in-the-loop mission simulation is not provisioned here as of this entry's date. This record supersedes DEC-014: DEC-014's original text is retained verbatim for audit history but is no longer the active authority for the `hardware-in-loop:sitl_mission` subject. Accepted on the same terms DEC-013/DEC-019 state, and must itself be superseded rather than extended once simulation is provisioned. | architect | hardware-in-loop:sitl_mission | active | DEC-014
