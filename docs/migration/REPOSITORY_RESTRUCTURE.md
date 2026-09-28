# Repository restructure

## Purpose

The existing CFS/Reels application and its R&D artifacts were moved intact beneath `legacy/`. A separate, empty `amix/` boundary now exists for the future AMIX product. No pipeline algorithm, prompt, role, model setting, framing rule, or render behavior was intentionally changed.

## Root boundary

Repository infrastructure remains at the repository root:

- `.git/`
- `.gitignore`
- `.venv/`
- root `README.md`
- `legacy/`
- `amix/`
- `docs/`

The existing `.venv/` was deliberately not moved or duplicated because virtual environments may contain absolute paths. It remains ignored and is not an AMIX environment.

## Relocated legacy application

The former root application directories and files now live directly under `legacy/`, including:

- `reels_factory/`
- `scripts/`
- `roles/`
- `prompts/`
- `schemas/`
- `tests/`
- `assets/`
- `data/`
- `run_pipeline.py`
- `config.yaml`
- `config.example.yaml`
- `requirements.txt`
- `requirements-dev.txt`
- the former `README.md`

Generated media was moved on the same filesystem with its containing `data/` tree. It was not copied or added to Git.

## Known consequences of relocation

The legacy application was written with the repository root as its working directory. Relocation may therefore affect:

- commands documented as `python run_pipeline.py ...`;
- scripts that compute the repository root from `Path(__file__).parents[...]`;
- hard-coded paths beginning with `data/`, `assets/`, `roles/`, `prompts/`, or `scripts/`;
- imports when a script is launched from the new repository root instead of `legacy/`;
- setup scripts that expect `.venv` beside `run_pipeline.py`;
- the root `.venv`, whose installed paths and activation assumptions still refer to the pre-move layout;
- ignored/generated data whose stored metadata names old repository-relative paths;
- one-off scripts under `legacy/data/tmp_*` that derive root depth from their historical location.

These consequences are documented rather than patched. No compatibility layer or broad path rewrite was introduced.

## Git and media handling

Git history remains in the original root `.git/`. Files were moved rather than duplicated so Git can infer renames. Root ignore rules were extended for `legacy/` so the relocated virtual outputs, media, caches, local configuration, and temporary render directories remain ignored.

## AMIX scope

`amix/` contains directory scaffolding and a short README only. No product framework, dependencies, application code, database, UI, API, packaging system, or model integration has been initialized.
