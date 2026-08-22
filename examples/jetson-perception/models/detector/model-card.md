---
model_name: detector
version: "1.0.0"
task: object_detection
input_shape: [1, 3, 640, 640]
precision: fp16
target_runtime: tensorrt
target_device: Jetson Orin Nano
dataset_id: campus-patrol-v3
dataset_license: CC-BY-4.0
trained_commit: "0123456789abcdef0123456789abcdef01234567"
eval_metric: mAP50
eval_value: 0.91
eval_dataset_split: validation-2026-05
known_failure_modes: "Reduced recall in dense fog and motion blur"
owner: perception-team
artifact_path: models/detector/detector.engine
latency_p95_ms: 30.0
latency_percentile: 95
---

# Detector model

Reviewed detector for the example patrol mission.
