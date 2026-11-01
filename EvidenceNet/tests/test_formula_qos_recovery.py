"""Run independent QoS recovery with local scheduler/interpreter doubles."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT/'migration/horeka-formula-semantics-20261027/recover_qos_submit.sh'


def harness(tmp_path):
    script = tmp_path/'recover_qos_submit.sh'
    shutil.copyfile(SCRIPT, script)
    (tmp_path/'bundle.tgz').write_bytes(b'frozen archive fixture')
    (tmp_path/'frozen.txt').write_text('frozen extracted file\n')
    sha = lambda name: hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()
    (tmp_path/'deployment.sha256').write_text(sha('bundle.tgz')+'  bundle.tgz\n')
    (tmp_path/'bundle_contents.sha256').write_text(sha('frozen.txt')+'  frozen.txt\n')
    (tmp_path/'unpacked_bundle.sha256').write_text(sha('bundle.tgz')+'\n')
    (tmp_path/'submitted_formula_job.txt').write_text('5215293\n')
    (tmp_path/'queue').write_text('5215293|PENDING\n')
    (tmp_path/'accounting').write_text('5215293|COMPLETED|\n')
    (tmp_path/'checkpoint').write_text('incomplete\n')
    bin_dir = tmp_path/'bin'; bin_dir.mkdir()
    commands = {
        'squeue': '#!/bin/bash\ncat queue\nif [[ -e queue_error ]]; then exit 1; fi\n',
        'sacct': '#!/bin/bash\nprintf "sacct\\n" >> events\ncat accounting\n',
        'sbatch': '''#!/bin/bash
printf '%s\n' "$*" >> calls
if [[ -e qos_fail ]]; then echo 'sbatch: error: QOSMaxSubmitJobPerUserLimit' >&2; exit 1; fi
if [[ -e malformed ]]; then echo not-an-id; exit 0; fi
if [[ $* == *reading_smoke.sbatch* ]]; then echo 700001; else echo 700002; fi
''',
        'python': '''#!/bin/bash
printf '%s\n' "$*" >> events
if [[ $1 == prepare_reading_smoke.py && -e prepare_fail ]]; then exit 9; fi
if [[ $1 == - ]]; then
  cat >/dev/null
  if [[ -e checkpoint_error ]]; then exit 7; fi
  cat checkpoint
fi
''',
    }
    for name, content in commands.items():
        path = bin_dir/name; path.write_text(content); path.chmod(0o700)
    env = dict(os.environ, PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],
               QOS_RECOVERY_PYTHON=str(bin_dir/'python'))
    def run():
        return subprocess.run(['bash', str(script)], cwd=tmp_path, env=env,
                              capture_output=True, text=True)
    return run


def calls(tmp_path):
    path = tmp_path/'calls'
    return path.read_text().splitlines() if path.exists() else []


def test_pending_primary_only_submits_missing_reading_and_reuses_ids(tmp_path):
    run = harness(tmp_path)
    first = run()
    assert first.returncode == 0, first.stderr
    assert calls(tmp_path) == ['--parsable reading_smoke.sbatch']
    assert not (tmp_path/'submitted_continuation_job.txt').exists()
    assert 'remains in squeue (PENDING)' in first.stdout
    assert run().returncode == 0
    assert len(calls(tmp_path)) == 1
    assert (tmp_path/'submitted_formula_job.txt').read_text() == '5215293\n'


def test_qos_failure_prints_saved_ids_and_remains_retryable(tmp_path):
    run = harness(tmp_path); (tmp_path/'qos_fail').touch()
    result = run()
    assert result.returncode != 0
    assert 'formula=5215293' in result.stdout and 'reading_smoke=NOT_SUBMITTED' in result.stdout
    assert not (tmp_path/'submitted_reading_smoke_job.txt').exists()
    (tmp_path/'qos_fail').unlink()
    assert run().returncode == 0
    assert len(calls(tmp_path)) == 2


def test_terminal_incomplete_primary_submits_one_bounded_continuation(tmp_path):
    run = harness(tmp_path); (tmp_path/'queue').write_text('')
    (tmp_path/'accounting').write_text('5215293|TIMEOUT|\n')
    result = run()
    assert result.returncode == 0, result.stderr
    assert calls(tmp_path) == ['--parsable reading_smoke.sbatch', '--parsable formula.sbatch']
    assert (tmp_path/'submitted_continuation_job.txt').read_text() == '700002\n'
    assert run().returncode == 0 and len(calls(tmp_path)) == 2


def test_terminal_complete_checkpoint_does_not_allocate_continuation(tmp_path):
    run = harness(tmp_path); (tmp_path/'queue').write_text(''); (tmp_path/'checkpoint').write_text('complete\n')
    result = run()
    assert result.returncode == 0 and 'already complete' in result.stdout
    assert calls(tmp_path) == ['--parsable reading_smoke.sbatch']


def test_absent_or_nonterminal_accounting_never_implies_completion(tmp_path):
    run = harness(tmp_path); (tmp_path/'queue').write_text('')
    for accounting in ('', '5215293|RUNNING|\n', '123|COMPLETED|\n'):
        (tmp_path/'accounting').write_text(accounting)
        result = run()
        assert result.returncode != 0
        assert not (tmp_path/'submitted_continuation_job.txt').exists()
    assert calls(tmp_path) == ['--parsable reading_smoke.sbatch']


def test_checkpoint_validation_error_preserves_ids_without_continuation(tmp_path):
    run = harness(tmp_path); (tmp_path/'queue').write_text(''); (tmp_path/'checkpoint_error').touch()
    result = run()
    assert result.returncode == 7
    assert 'reading_smoke=700001' in result.stdout
    assert not (tmp_path/'submitted_continuation_job.txt').exists()


def test_invalid_saved_id_or_changed_frozen_file_stops_before_submission(tmp_path):
    run = harness(tmp_path)
    (tmp_path/'submitted_formula_job.txt').write_text('bad-id\n')
    assert run().returncode != 0 and calls(tmp_path) == []
    (tmp_path/'submitted_formula_job.txt').write_text('5215293\n')
    (tmp_path/'frozen.txt').write_text('changed\n')
    assert run().returncode != 0 and calls(tmp_path) == []


def test_prepare_failure_does_not_submit_or_hide_primary(tmp_path):
    run = harness(tmp_path); (tmp_path/'prepare_fail').touch()
    result = run()
    assert result.returncode == 9 and calls(tmp_path) == []
    assert 'formula=5215293' in result.stdout
