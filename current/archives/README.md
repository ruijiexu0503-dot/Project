# Local archive records

Only this documentation is tracked here. JSON/JSONL archive manifests are
collected in `current/json/`, ignored and preserved on the local disk.
They describe this workspace's cleanup and are not pipeline input configs.

`current/json/launchers_20261009.json` records 69 archived sbatch files and 27 retained
launchers. Preview recovery with `python current/restore_launchers.py`;
restore a selected file with `--path ... --apply`.

`current/json/tracked_files_20261004.json` records 88 source-to-archive entries covering
260 previously tracked files. `current/json/selection.json` holds historical
cleanup selections; the superseded-script and experiment archive manifests
record their respective local archives.

Recovery tools require both the local manifests and the payload under
`_archive/`. A fresh checkout does not include either. Previously committed
files can also be recovered from Git history by their original paths.
