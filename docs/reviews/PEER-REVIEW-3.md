# Final adversarial review — `c01dce1~1..HEAD`

## Findings

### 1. Blocker — RECURRENCE: the release aggregate accepts forged decision authority

**Location:** `src/hexvision/orchestration.py:141-166`

The newly green path treats any truthy `result.measurements["decision_id"]` as an
authorised decision.  It neither receives `Config` nor reads the configured
decision log, validates an ID pattern, checks whether the ID exists, checks that
the record applies to this gate, nor checks any withdrawal/revocation state.
The name `authorised_declared_skips` is therefore a false assertion rather than
a verified measurement.

I ran a fake allowlisted pack whose only gate calls
`GateResult.skipped_declared(..., decision_id=<claim>)` and performs no
validation.  All of these claims produced `status="passed"` and exit code `0`:

```text
DEC-999999  -> {'forged-pack/forged-skip': 'DEC-999999'}
nonsense    -> {'forged-pack/forged-skip': 'nonsense'}
DEC-013     -> {'forged-pack/forged-skip': 'DEC-013'}
```

The last case did not require a decision log in the temporary repository, so it
cannot establish that DEC-013 applies to this fake gate.  The relevant
regression test only supplies the positive literal `DEC-777`
(`tests/core/test_release_orchestration.py:276-296`); it has no nonexistent,
malformed, unrelated, or withdrawn-ID negative case.

This is a **RECURRENCE** of the self-reported-authority defect class: the
previously fixed principle is defeated again at a new release aggregation
boundary.  An active pack can turn a real unavailable/failing control into a
green release simply by supplying a nonempty string.

**Required fix:** make aggregation verify each declared skip against the
configured decision-log parser at this boundary (or pass a typed,
non-forgeable, already-verified authority object from a single verifier).
Verification must require an exact ID, an exact gate/runner subject binding, and
an active/non-withdrawn record.  Do not use a truthiness check as authority.
Add the four negative cases exercised above, plus a revoked record, as release
aggregate tests.

### 2. Major — RECURRENCE: HIL decision matching authorises unrelated and withdrawn records

**Location:** `src/hexvision/robotics/hardware_in_loop.py:318-331`

Per-runner resolution is an improvement, but `_authorising_decision` does not
actually require a record to name a runner.  It authorises a runner when its
name is a substring of the delimiter-joined *entire record*, including the
identifier, reason, and reviewer:

```python
if gate_name in schema.delimiter.join(record.cells) and pattern.fullmatch(identifier):
```

I created a temporary log containing
`DEC-201 | alpha_beta subsystem is unrelated to the alpha runner`.  With an
absent runner named `alpha`, the gate returned
`skipped-declared`, `decision_id="DEC-201"`, and exit code 1.  I also created a
log with an initial `DEC-202` authorising `alpha`, followed by a valid
`DEC-203` record saying `DEC-202 is withdrawn; alpha runner must execute`.
The gate still returned `skipped-declared`, `decision_id="DEC-202"`.

The newly introduced aggregate in finding 1 then converts either result into a
green release because its decision ID is nonempty.  There is no status or
supersession/revocation field in the decision-log record model
(`src/hexvision/decision_log.py:36-95`), and no lifecycle check here.

This is a **RECURRENCE** of authority being accepted without verification of
the authority's actual subject and validity.  A stray word such as
`alpha_beta`, or an obsolete record retained for audit history, can excuse
missing hardware evidence.

**Required fix:** extend the authority record schema with explicit,
machine-readable subject(s) and lifecycle state (or an immutable
supersession relation), then compare the configured runner name exactly.  The
parser/verifier should return only active records and be shared by HIL and
release aggregation.  Add negative tests for substring collisions, reviewer
text collisions, and withdrawn/superseded IDs.

### 3. Major — RECURRENCE: `agent-validation` is a successful no-op when all governed definitions are removed

**Location:** `src/hexvision/agent_validation.py:304-316, 216-239`

`_expected_paths` requires the two directories to exist but permits both glob
results to be empty.  The empty tuple then produces no findings and the
validator returns `PASSED`; it has no reviewed inventory or nonzero cardinality
requirement.

I copied the repository under `/tmp`, deleted every file below
`.claude/agents` and `.claude/skills` while retaining both directories, and
ran the real Make target.  It exited 0 with:

```json
{"status":"passed","exit_code":0,
 "measurements":{"agents":0,"skills":0,"definitions":0,"discovery":[]}}
```

Deleting `.claude/agents` itself was correctly `blocked` with exit 2.  Thus
removing the contents, rather than the directory, bypasses the newly wired
control completely.  Existing tests cover missing directories
(`tests/aqa/test_agent_definition_validation.py:190-205`) but not empty
directories.

This is a **RECURRENCE** of a governed capability being wired but able to run
as a no-op.  It matters because the CI job and `pre-pr` target provide an
apparent assurance that agent/skill definitions were checked even after all
such inputs have disappeared.

**Required fix:** make policy state the expected minimum/count or, preferably,
a reviewed manifest of required agent and skill artifact paths; fail when the
discovered set does not satisfy it.  Add an integration test invoking
`make agent-validation` against empty-but-present directories and expecting a
nonzero verdict.

### 4. Minor — human-readable release output omits the authorised skip identities

**Location:** `src/hexvision/orchestration.py:158-165`;
`src/hexvision/cli.py:89-97`

The aggregate stores the gate-to-decision mapping only in JSON measurements.
The non-JSON CLI renderer prints only `gate`, `status`, `summary`, and
findings.  I rendered an aggregate containing
`{'fake-pack/hidden-details': 'DEC-999999'}` without `--json`; the complete
operator output was:

```text
domain-gates: passed — every active pack domain gate passed; 1 declared unavailable under recorded decisions
```

A status-only consumer sees a plain green result.  A human-summary reader is
told that one skip exists, so this is not a fully silent skip, but cannot tell
which gate was excused or which decision supposedly authorised it.  That
contradicts the DEC-015 claim that the aggregate “lists each one against the
decision” (`docs/decision-log.md:39`).  The test only asserts the structured
measurement and count in the summary
(`tests/core/test_release_orchestration.py:291-296`).

**Required fix:** in non-JSON output, print one concise line per authorised
skip with `pack/gate` and its decision ID.  Keep the structured measurement as
well.

## Adversarial checks with no additional finding

- **A gate can report `PASSED` while doing nothing:** confirmed.  A fake
  `Gate` returning `GateResult.passed(...)` without inspecting its `Config`
  produced `passed`/exit 0.  `GateResult.passed` deliberately permits this
  shape (`src/hexvision/gates/model.py:221-243`).  This generic extensibility
  boundary predates the reviewed aggregation change and cannot by itself prove
  gate-specific work, so I have not counted it as a separate scoped finding.
  Its declared-skip variant is the exploitable new release-authority failure in
  finding 1.
- **Mixed HIL authority:** confirmed safe for the direct HIL result.  With
  absent `alpha` authorised by DEC-101 and absent `beta` unauthorised, the gate
  returned `blocked`/exit 2, `missing={"alpha":"DEC-101","beta":null}`, and
  named `beta` in its finding.  This is the correct fail-closed outcome for a
  partially authorised runner set (`src/hexvision/robotics/hardware_in_loop.py:211-234`).
- **Release-order enforcement:** the tests genuinely reject an extra local
  `pre-pr` prerequisite absent from the configured order: an isolated-copy run
  of `test_pre_pr_chains_configured_targets_in_exact_configured_order` failed
  with “Left contains one more item: 'extra'”.  An isolated CI job `extra`
  invoking `make extra` outside the configured order likewise failed
  `test_ci_gate_sequence_equals_the_configured_pre_pr_order`.  A standalone
  Make target not placed in `pre-pr` is intentionally outside this contract.
- **Missing definition directories:** as noted in finding 3, this condition
  blocks rather than passes.
- **Lint/type hardening:** `.venv/bin/ruff check src tests` and
  `.venv/bin/mypy` both passed.  I found no additional hardcoded or
  backwards-compatibility defect in the scoped Ruff/mypy/`pytest.raises`
  changes.

## Tests run

```text
.venv/bin/python -m pytest -q \
  tests/core/test_release_orchestration.py \
  tests/robotics/test_hardware_and_pack.py \
  tests/aqa/test_agent_definition_validation.py \
  tests/governance/test_governance_meta.py \
  tests/aqa/test_exit_code_authority.py

62 passed in 10.07s
```

All exploit scripts and altered copies were created only under `/tmp`; no file
under `/home/user/workspace/hex-vision` was modified.
