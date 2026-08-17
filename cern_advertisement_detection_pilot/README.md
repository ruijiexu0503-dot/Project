CERN Courier advertisement detection pilot

This experiment runs TransDLANet inference on split single-page images from
the CERNCourier2022NovDec-digitaledition to evaluate advertisement detection.

See `src/run_pilot.py --help` for usage. Provide a TransDLANet implementation
and checkpoint via `--model-dir` / `--checkpoint` or set up the Python package
in your environment. A Slurm batch script is provided for GPU runs.
