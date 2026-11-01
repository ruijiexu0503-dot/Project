"""Regression: sbatch --chdir must not be undone by SLURM_SUBMIT_DIR."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'migration/horeka-dev-retry-20261029/dev.sbatch'


@pytest.mark.parametrize('kind,run',[('top10','top10-navigation-20261029'),('selection','query-evidence-20261029')])
@pytest.mark.parametrize('preflight',[True,False])
def test_explicit_experiment_root_overrides_wrong_submit_dir(tmp_path,kind,run,preflight):
    project=tmp_path/'Project';work=project/'remote_runs'/run;work.mkdir(parents=True)
    wrong=tmp_path/'wrong-submit-dir';wrong.mkdir()
    (work/'payload').write_text('payload')
    (work/'deployment.sha256').write_text(hashlib.sha256(b'payload').hexdigest()+'  payload\n')
    python=project/'EvidenceNet/.venv_qwen/bin/python';python.parent.mkdir(parents=True)
    log=tmp_path/'calls.jsonl'
    python.write_text('#!'+sys.executable+'\nimport json,os,sys\nfrom pathlib import Path\n'
        'with open(os.environ["CALL_LOG"],"a") as f:f.write(json.dumps({"cwd":str(Path.cwd()),"args":sys.argv[1:]})+"\\n")\n')
    python.chmod(0o755)
    script=tmp_path/'dev.sbatch'
    script.write_text(SCRIPT.read_text().replace('/hkfs/home/project/hk-project-p0025545/dv3352/Project',str(project)))
    args=['bash',str(script),kind]+(['--preflight'] if preflight else [])
    r=subprocess.run(args,cwd=wrong,env={**os.environ,'SLURM_SUBMIT_DIR':str(wrong),'CALL_LOG':str(log)},capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    calls=[json.loads(x) for x in log.read_text().splitlines()]
    assert len(calls)==(1 if preflight else 3)
    assert all(c['cwd']==str(work) for c in calls)
    assert 'payload: OK' in r.stdout
