# Lint and assertion hardening report

## Scope and approach

This change closes the outstanding lint-strictness recommendation with targeted test-correctness changes rather than broad style churn. It enables Ruff's pytest, import-hygiene, and annotation rule families; hardens every PT011 assertion with an observed error-message match; applies all PT006 parameter-name fixes; and records the limited typing boundary that remains dynamically typed.

## PT011 assertion hardening

I first executed the production operations directly and recorded their actual `ValueError` messages, then ran the affected pytest modules after adding the assertions. The probe command was:

```sh
.venv/bin/python -c '<imports and each failing production call>'
```

It emitted these real message fragments:

```text
logging-invalid-level: unknown log level 'BOGUS'; expected one of: CRITICAL, DEBUG, ERROR, FATAL, INFO, NOTSET, WARN, WARNING
logging-invalid-format: unknown log format 'bad'; expected one of: json, text
severity-unknown: unknown severity 'unknown'; expected one of: Blocker, Major, Minor, Info
passed-with-finding: gate 'x' reported PASSED while carrying 1 blocking finding(s); a passing gate with Major+ findings is a fail-open bug, not a warning
target-empty-command: target 'x' declares an empty command
target-missing-rationale: target 'x' opts out of fail-closed behaviour without a rationale; an unexplained exception is indistinguishable from a mistake
failed-empty-findings: gate 'g' failed without recording a finding; every factual claim is either mechanically measured here or absent
```

The model-card parser probe emitted:

```text
model-card-1: model card must begin with a front-matter delimiter
model-card-2: model card front matter has no closing delimiter
model-card-3: invalid front-matter key 'model name' at line 2
model-card-4: unsupported YAML construct at model card line 2
model-card-5: unclosed quoted scalar at model card line 2
model-card-6: empty list value for 'name'
```

| PT011 test assertion | Pinned observed message regex | Verification |
| --- | --- | --- |
| `test_logging_rejects_invalid_configuration` | `unknown log level 'BOGUS'` or `unknown log format 'bad'`, selected per parameter | Direct production probe and focused pytest run |
| `test_model_rejections_sorting_and_target_spec_validation`: unknown severity | `unknown severity 'unknown'` | Direct production probe and focused pytest run |
| Same test: passing result carrying a finding | `reported PASSED while carrying` | Direct production probe and focused pytest run |
| Same test: empty target command | `declares an empty command` | Direct production probe and focused pytest run |
| Same test: non-fail-closed target missing rationale | `opts out of fail-closed behaviour` | Direct production probe and focused pytest run |
| `test_logging_rejects_unknown_configuration` | `unknown log level 'NOPE'` or `unknown log format 'binary'`, selected per parameter | Direct production behavior and focused pytest run |
| `test_gate_result_serialises_and_sorts_findings` | `failed without recording a finding` | Direct production probe and focused pytest run |
| `test_front_matter_rejects_ambiguous_or_malformed_yaml` | Scenario-specific parser fragments listed above | Per-input direct parser probe and focused pytest run |

Focused verification command and actual result:

```sh
.venv/bin/python -m pytest -q tests/core/test_baseline_interfaces.py tests/robotics/test_core_execution.py tests/robotics/test_model_card.py
................................................................         [100%]
64 passed in 7.79s
```

## PT006 fixes

Ruff's supported unsafe pytest-parameter-name fix was applied after the manual PT011 changes. It converted the five string-form parameter names to tuples in:

1. `tests/core/test_baseline_interfaces.py` (one remaining PT006 after the manually edited assertion parameterization was already corrected)
2. `tests/core/test_dispatch_registry_branches.py`
3. `tests/core/test_publication.py`
4. `tests/robotics/test_model_card.py`
5. The initial baseline count also included the assertion parameterization corrected manually in `tests/core/test_baseline_interfaces.py`.

The final PT-only check was clean:

```text
All checks passed!
```

## Enabled Ruff protection

`[tool.ruff.lint] select` now permanently includes:

- `PT` for pytest correctness/style, including the PT011 and PT006 protections remediated here.
- `TID` for import hygiene and future relative-import drift. The baseline and final checks had zero TID findings.
- `ANN` for annotation completeness.

### Annotation disposition

All 23 source ANN401 findings are addressed. Concrete values now use precise annotations where the type is known: CLI payloads and log context use `object`, logging streams use `TextIO`, diagnostics receive `Config`, latency roots use `Path`, and scalar validation helpers use `object` plus their existing runtime narrowing.

The five `Config` accessor boundary annotations now use the documented `ConfigValue` alias. That alias remains `Any` intentionally and is explicitly commented: TOML permits heterogeneous scalar, list, table, and date-like values, while every policy consumer validates its required concrete shape before use. Replacing that public dynamic configuration boundary with `object` caused type failures across callers that legitimately require lists, mappings, numeric values, and strings; a schema-derived typed-config redesign is outside this lint-hardening change. This is the only retained source-level dynamic type and is named and justified rather than suppressed.

The tests-tree per-file ignore adds exactly these new codes:

```toml
"tests/**/*.py" = ["S101", "PLR2004", "ARG001", "ANN001", "ANN401"]
```

Its adjacent comment explains that pytest injects runtime fixture factories whose callable signatures static analysis cannot see. No source-tree annotation ignore was added. The five test-local `ANN202` return findings were fixed with actual generator, gate-sequence, and target-map return types rather than ignored.

## Mypy strictness

Enabled explicitly (and kept explicit even if the current `strict = true` bundle implies them):

- `disallow_any_generics = true`
- `disallow_any_unimported = true`
- `disallow_subclassing_any = true`

A combined check of those flags was clean:

```text
Success: no issues found in 73 source files
```

I did not enable the following flags because making them clean would require a broad, unrelated rewrite or type suppressions:

| Flag | Observed result | Reason left off |
| --- | --- | --- |
| `disallow_any_decorated` | `Found 37 errors in 16 files` | Existing pytest/decorator transformations erase callable signatures in test infrastructure. |
| `disallow_any_expr` | `Found 1757 errors in 57 files` | Existing dynamic TOML/JSON/configuration and structured test-data paths need a deliberate schema migration, not assertion-lint churn. |
| `disallow_any_explicit` | `Found 171 errors in 36 files` | Existing typed containers that represent externally parsed heterogeneous data need an incremental schema program. |

No new `type: ignore` comments were added for these options.

## Validation

All required validations were executed in this worktree:

```sh
.venv/bin/ruff check .
All checks passed!

.venv/bin/ruff format --check .
76 files already formatted

.venv/bin/mypy src tests
Success: no issues found in 73 source files

.venv/bin/python -m pytest -q
455 passed in 49.15s
```

Coverage was measured separately through the same commands used by the coverage gate:

```text
collected 455 items
455 passed in 52.77s
Required test coverage of 90.0% reached. Total coverage: 94.37%
coverage: passed — per-file coverage floors are met
```

I also executed `make pre-pr`; it exited 0 and ended with:

```text
pre-PR validation complete — every configured CI gate has passed locally.
```

## Open items

There are no remaining PT, TID, or active ANN findings, and no test-count reduction. The only intentionally retained dynamic type is the documented `ConfigValue` boundary described above. The three rejected mypy flags remain off for the concrete reasons and observed error counts recorded in this report.
