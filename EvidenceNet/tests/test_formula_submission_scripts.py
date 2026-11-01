"""Exercise submission state handling without SSH or Slurm side effects."""
from pathlib import Path
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT/'migration/horeka-formula-semantics-20261027'


def setup(tmp_path):
    text = (PACKAGE/'finalize_submit.sh').read_text()
    function = text[text.index('formula_submit() {'):text.index('formula_first=$(formula_submit')]
    fake = tmp_path/'sbatch'
    fake.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> calls\nif [[ -e fail ]]; then exit 1; fi\nif [[ -e malformed ]]; then echo bad-id; else echo 12345; fi\n')
    fake.chmod(0o700)
    env = dict(os.environ, PATH=str(tmp_path)+os.pathsep+os.environ['PATH'])
    def run(commands):
        return subprocess.run(['bash', '-c', 'set -euo pipefail\n'+function+commands], cwd=tmp_path,
                              env=env, capture_output=True, text=True)
    return run


def test_saved_jobs_not_resubmitted_and_continuation_is_afterany(tmp_path):
    run = setup(tmp_path)
    result = run('formula_submit formula formula.sbatch\nformula_submit continuation formula.sbatch 12345\nformula_submit formula formula.sbatch\n')
    assert result.returncode == 0, result.stderr
    calls = (tmp_path/'calls').read_text().splitlines()
    assert len(calls) == 2 and '--dependency=afterany:12345' in calls[1]
    assert (tmp_path/'submitted_formula_job.txt').read_text().strip() == '12345'


def test_failed_or_malformed_submission_not_recorded(tmp_path):
    run = setup(tmp_path)
    for marker in ('fail', 'malformed'):
        (tmp_path/marker).touch()
        assert run('formula_submit formula formula.sbatch\n').returncode != 0
        assert not (tmp_path/'submitted_formula_job.txt').exists()
        (tmp_path/marker).unlink()
    (tmp_path/'submitted_formula_job.txt').write_text('bad-id\n')
    count = len((tmp_path/'calls').read_text().splitlines())
    assert run('formula_submit formula formula.sbatch\n').returncode != 0
    assert len((tmp_path/'calls').read_text().splitlines()) == count


def test_every_checked_deployment_file_is_uploaded():
    checked = {line.split(None, 1)[1] for line in (PACKAGE/'deployment.sha256').read_text().splitlines()}
    text = (PACKAGE/'resume_submit.sh').read_text()
    loop = re.search(r'for formula_file in (.*?); do', text).group(1).split()
    assert checked <= set(loop)
