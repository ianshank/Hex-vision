---
title: Hex-vision Gate Demo
sdk: gradio
sdk_version: 5.24.0
app_file: examples/space/app.py
python_version: 3.11
license: apache-2.0
pinned: false
---

# Hex-vision Gate Demo

This Space runs the real Hex-vision Jetson pack against bundled reference and fault scenarios. It does not fabricate verdicts: the app copies sample repository evidence to a temporary directory, resolves the standard Hex-vision configuration there, and runs the pack’s actual domain gates through the shared gate runner.

## What the demo shows

Choose one of the scenarios and run the gates:

- **Reference evidence** contains a reviewed model card, paired TensorRT artefact, deterministic evaluation record, and valid mission envelope.
- **Broken evidence** contains invalid provenance, runtime, evaluation, and mission evidence so the actual gates return findings.
- **Missing evaluation evidence** removes the evaluation-run record for a reviewed model, causing the determinism gate to report that it could not establish the required evidence.

The hardware-in-the-loop gate also demonstrates the explicit declared-absence status when its configured runners are unavailable. The result table and JSON panel preserve the four GateStatus values: `passed`, `failed`, `blocked`, and `skipped-declared`.

## Run locally

From this repository root:

```bash
uv sync --extra dev
pip install -r examples/space/requirements.txt
python examples/space/app.py
```

When deploying this folder independently as a Space, retain `examples/space/sample/` beside `app.py`; `requirements.txt` installs the published Hex-vision package. The demo is a repository-evidence viewer, not vehicle control, hardware provisioning, safety certification, or publication authority.

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
