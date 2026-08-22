# Jetson perception example

The top-level detector card, TensorRT artifact, repeatable evaluation record and
patrol mission pass the robotics gates when copied into a repository using the
default configuration. The `broken/` tree is intentionally excluded by the
default globs and demonstrates separate failures: missing model provenance and
unsupported runtime, incomplete/non-identical evaluation seeds, too few runs,
and invalid mission envelope values.

The eval-run record uses schema version 1: `schema_version`, `model_name`, and a
`runs` list. Every run records `metric_value`, `python_seed`, `numpy_seed`, and
`framework_seed`; all seed values must remain identical across the list.
