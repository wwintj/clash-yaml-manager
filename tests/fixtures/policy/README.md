# Preserve compatibility goldens

`base.yaml` is a public, synthetic Custom YAML fixture. `preserve.yaml` and
`preserve-default.sha256` were captured by running `core/yaml_utils.py` from the
pre-policy commit `24fb40141c8ff85345c78864b8f38c3d49f5ff5e`, before integrating
Policy Engine. The default source is the unchanged `defaults/default.yaml`.

The nodes/structured assignments and selected `media` group are defined in
`tests/test_policy_engine.py`. Example UUIDs/endpoints are test fixtures only.
The tests compare exact output bytes (custom) or SHA256 (default) for both omitted
policy and explicit Preserve / Preserve. Output random filenames do not affect
YAML bytes. Do not regenerate goldens from the new generator to mask a regression.
