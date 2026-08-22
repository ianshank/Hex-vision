---
model_name: bad-detector
version: "0.1.0"
task: object_detection
input_shape: [1, 3, 640, 640]
precision: fp8
target_runtime: unknown-runtime
target_device: Jetson Nano
trained_commit: deadbeef
eval_metric: mAP50
eval_value: not-a-number
eval_dataset_split: ""
owner: nobody
artifact_path: models/bad-detector/missing.engine
latency_p95_ms: 200
---
