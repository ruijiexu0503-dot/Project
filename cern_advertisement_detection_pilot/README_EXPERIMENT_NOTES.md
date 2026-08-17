Experiment notes and instructions

- The repository does not include a TransDLANet implementation. Provide one by:
  - installing a transdlanet Python package into the environment, or
  - placing a local implementation under `external/models/TransDLANet` and ensuring it exposes `load_model` and `model.predict(image_path)`.

- Before running, confirm the mapping of model output classes to advertisement (pass `--ad-classes`).
- The pilot script writes:
  - `cern_advertisement_detection_pilot/predictions.jsonl`
  - `cern_advertisement_detection_pilot/visualizations/` (per-page images)
  - `cern_advertisement_detection_pilot/visualizations/index.html`
  - `cern_advertisement_detection_pilot/summary.md`
