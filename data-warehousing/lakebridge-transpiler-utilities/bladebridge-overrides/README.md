# BladeBridge sample overrides

JSON snippets that override BladeBridge’s default mapping of legacy workflow components to PySpark / job structure. Nothing in this folder is executed on its own; you **reference** or **copy** these into a pipeline run.

## Replace placeholder values

Before you use an override file, open it and replace every **angle-bracket placeholder** in **`config_variables`**. 


## Files

| File | Use when |
| --- | --- |
| `sample_override_ssis.json` | SSIS: `config_variables`, `workflow_specs` for tasks like `EXECUTE_SQL_TASK`, `EXECUTE_PACKAGE`, `PIPELINE`, etc. Contains the placeholders described under **Replace placeholder values**—edit before use. |
| `sample_override_informatica.json` | Informatica: `SESSION`, `SUBJOB`, `WORKLET`, `SET_VARIABLE`, `skip_component_types`, etc. Contains the placeholders described under **Replace placeholder values**—edit before use. |
| `sample_override_datastage.json` | DataStage: job/stage workflow mappings and config variables. Contains the placeholders described under **Replace placeholder values**—edit before use. |

## How to use

Finish **Replace placeholder values** for whichever sample (or copy) you pass to Lakebridge—do not skip this step.

1. **Quick path:** From a pipeline directory, pass `-r` / `--overrides-file` with the path to one of these files (or a **copy** you edited).
2. **Interactive Lakebridge:** When prompted for a BladeBridge override file, paste the path or press enter to skip and use the pipeline’s default `sample_override.json`.
3. **Customize:** Copy the nearest sample, rename it, and adjust `workflow_specs`, `skip_component_types`, and `config_variables` for your packages. Keep changes focused and compare against the sample as you go.

## What to change

- **Component types** your source uses that still map wrong → add or adjust entries under `workflow_specs` (or equivalent) in the JSON.
- **Noise or unsupported steps** you want BladeBridge to ignore → `skip_component_types` or analogous keys (Informatica sample shows the pattern).
- **Paths and conventions** (e.g. delta roots, task paths) → `config_variables` in your override JSON (all samples ship placeholders there).

For detailed BladeBridge configuration instructions, see the official Lakebridge documentation: [BladeBridge Configuration Guide](https://databrickslabs.github.io/lakebridge/docs/transpile/pluggable_transpilers/bladebridge/bladebridge_configuration/).
