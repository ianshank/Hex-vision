"""Interactive demonstration of the Hex-vision Jetson pack using real evidence gates."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import gradio as gr

import hexvision
from hexvision.config import load_config
from hexvision.gates.base import run_gate
from hexvision.packs.jetson import pack

_SAMPLE_ROOT = Path(__file__).parent / "sample"
_SCENARIOS = {
    "Reference evidence": "reference",
    "Broken evidence": "broken",
    "Missing evaluation evidence": "reference",
}
_TABLE_HEADERS = ["Verdict", "Gate", "Clause", "Exit code", "Summary"]


def _scenario_root(scenario: str, root: Path) -> None:
    """Prepare one concrete evidence tree for the selected scenario."""
    source_name = _SCENARIOS[scenario]
    source = _SAMPLE_ROOT / source_name
    if not source.is_dir():
        raise FileNotFoundError(f"bundled evidence is unavailable: {source}")
    shutil.copytree(source, root, dirs_exist_ok=True)
    (root / "docs").mkdir()
    (root / "docs" / "decision-log.md").write_text("", encoding="utf-8")
    if scenario == "Missing evaluation evidence":
        for record in root.glob("models/**/eval-runs.*"):
            record.unlink()


def run_demo(scenario: str) -> tuple[list[list[str | int]], dict[str, object]]:
    """Run the installed Jetson pack against real, temporary sample evidence."""
    with tempfile.TemporaryDirectory(prefix="hexvision-space-") as temporary:
        root = Path(temporary)
        _scenario_root(scenario, root)
        config = load_config(root=root)
        results = [run_gate(gate, config) for gate in pack.domain_gates(config)]
    rows = [
        [
            result.status.value,
            result.gate,
            result.clause or "",
            int(result.exit_code),
            result.summary,
        ]
        for result in results
    ]
    payload: dict[str, object] = {
        "package": hexvision.__name__,
        "scenario": scenario,
        "results": [result.to_dict() for result in results],
    }
    return rows, payload


with gr.Blocks(title="Hex-vision Gate Demo") as demo:
    gr.Markdown(
        "# Hex-vision Gate Demo\n"
        "Run the actual Jetson pack against bundled repository evidence. "
        "The output distinguishes policy failures from checks that could not inspect evidence."
    )
    scenario = gr.Radio(
        choices=list(_SCENARIOS),
        value="Reference evidence",
        label="Evidence scenario",
        info="Each option runs real gates on a temporary copy of the selected sample evidence.",
    )
    run = gr.Button("Run gates", variant="primary")
    verdicts = gr.Dataframe(
        headers=_TABLE_HEADERS,
        datatype=["str", "str", "str", "number", "str"],
        interactive=False,
        label="Gate verdicts",
    )
    details = gr.JSON(label="Structured GateResult evidence")
    gr.Markdown(
        "`passed` means the gate inspected evidence and met policy. "
        "`failed` means it found a violation. `blocked` means it could not inspect "
        "a required input or policy. `skipped-declared` makes an absent configured "
        "hardware runner explicit and remains non-passing."
    )
    run.click(run_demo, inputs=scenario, outputs=[verdicts, details])


if __name__ == "__main__":
    demo.launch()
