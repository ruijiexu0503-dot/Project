"""Exercise scheduler transitions without contacting Slurm or cancelling jobs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
DEPLOY=ROOT/'migration/horeka-dev-switch-20261029'
MOCK=r'''
import json,os,sys
from pathlib import Path
p=Path(os.environ['MOCK_STATE']);s=json.loads(p.read_text());a=sys.argv[1:];cmd=Path(sys.argv[0]).name
s['events'].append([cmd]+a);code=0
if s.get('deny_partition') and (cmd=='sinfo' or (cmd=='scontrol' and a[0]=='show')):
 print('Access/permission denied',file=sys.stderr);code=1
elif cmd=='squeue' and s.get('deny_queue'):
 code=1
elif cmd=='squeue':
 j=a[a.index('-j')+1]
 print(s['jobs'].get(j,{}).get('state','') if '-h' in a else 'scheduler estimate unavailable')
elif cmd=='scontrol' and a[0] in ('hold','release'):
 s['jobs'][a[1]]['held']=a[0]=='hold'
elif cmd=='sbatch':
 if s.get('reject'):code=1
 else:
  s['jobs']['6000001']={'state':'PENDING','held':True};print('6000001')
elif cmd=='scancel':
 if s.get('cancel_fail'):code=1
 else:
  assert s['jobs'][a[0]]['held'] and s['jobs'][a[0]]['state']=='PENDING'
  s['jobs'][a[0]]['state']='CANCELLED'
p.write_text(json.dumps(s));sys.exit(code)
'''


def run_switch(tmp_path,top='PENDING',reject=False,cancel_fail=False,deny_partition=False,deny_queue=False):
    remote=tmp_path/'remote';remote.mkdir()
    switch=tmp_path/'switch';switch.mkdir()
    script=(DEPLOY/'switch_remote.sh').read_text().replace(
        '/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs',str(remote))
    (switch/'switch_remote.sh').write_text(script)
    (switch/'dev.sbatch').write_text('# test payload\n')
    (switch/'switch.sha256').write_text(''.join(hashlib.sha256((switch/n).read_bytes()).hexdigest()+'  '+n+'\n'
        for n in ('switch_remote.sh','dev.sbatch')))
    for name,job in [('top10-navigation-20261029','5217494'),('query-evidence-20261029','5217479')]:
        d=remote/name;d.mkdir();(d/'submitted_job_id.txt').write_text(job+'\n')
        (d/'payload').write_text('test')
        (d/'deployment.sha256').write_text(hashlib.sha256(b'test').hexdigest()+'  payload\n')
    binpath=tmp_path/'bin';binpath.mkdir()
    mock=binpath/'scheduler';mock.write_text('#!'+sys.executable+'\n'+MOCK);mock.chmod(0o755)
    for name in ('scontrol','squeue','sacct','sinfo','sbatch','scancel'):(binpath/name).symlink_to(mock)
    state=tmp_path/'state.json'
    state.write_text(json.dumps({'jobs':{'5217494':{'state':top,'held':False},
        '5217479':{'state':'RUNNING','held':False}},'events':[],'reject':reject,'cancel_fail':cancel_fail,
        'deny_partition':deny_partition,'deny_queue':deny_queue}))
    env={**os.environ,'PATH':str(binpath)+':'+os.environ['PATH'],'MOCK_STATE':str(state)}
    result=subprocess.run(['bash',str(switch/'switch_remote.sh')],env=env,text=True,capture_output=True)
    return result,json.loads(state.read_text())


def test_pending_switch_holds_both_before_cancelling_and_releases_new(tmp_path):
    result,state=run_switch(tmp_path)
    assert result.returncode==0,result.stderr
    assert state['jobs']['5217494']['state']=='CANCELLED'
    assert state['jobs']['6000001']=={'state':'PENDING','held':False}
    assert not any(e[0]=='scancel' and e[1]=='5217479' for e in state['events'])


def test_rejected_dev_preserves_original_queue_job(tmp_path):
    result,state=run_switch(tmp_path,reject=True)
    assert result.returncode!=0
    assert state['jobs']['5217494']=={'state':'PENDING','held':False}
    assert not any(e[0]=='scancel' for e in state['events'])


def test_running_jobs_are_never_held_cancelled_or_duplicated(tmp_path):
    result,state=run_switch(tmp_path,top='RUNNING')
    assert result.returncode==0
    assert not any(e[0] in ('sbatch','scancel') or e[:2]==['scontrol','hold'] for e in state['events'])


def test_cancellation_failure_does_not_start_duplicate(tmp_path):
    result,state=run_switch(tmp_path,cancel_fail=True)
    assert result.returncode!=0
    assert state['jobs']['5217494']['held']
    assert state['jobs']['6000001']['held']


def test_partition_visibility_denial_does_not_block_submission(tmp_path):
    result,state=run_switch(tmp_path,deny_partition=True)
    assert result.returncode==0,result.stderr
    assert 'SWITCHED top10' in result.stdout
    assert state['jobs']['6000001']['held'] is False


def test_own_job_state_denial_prevents_all_mutations(tmp_path):
    result,state=run_switch(tmp_path,deny_queue=True)
    assert result.returncode!=0
    assert not any(e[0] in ('sbatch','scancel') or e[:2]==['scontrol','hold'] for e in state['events'])
