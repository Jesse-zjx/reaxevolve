#!/usr/bin/env python3
"""Historical rediscovery runner (negative control B).

Calls the discovery-era dispatcher at RN/validate_candidate.py. That file is
no longer on the live tool path; the scored results in comparison.json /
results/ are the record. Do not treat this script as a current-method replay.
To regenerate the report from those results:

    python experiments/rediscovery/render_report.py
"""
import os, sys, json, time, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
_d = HERE
while _d != '/' and not os.path.isfile(os.path.join(_d, 'tools', 'chem_paths.py')):
    _d = os.path.dirname(_d)
sys.path.insert(0, os.path.join(_d, 'tools'))
import chem_paths as _CP  # noqa: E402
RN, WS, PYBIN = _CP.RN, _CP.ROOT, _CP.PYBIN


def shard_jobs(jobs, shard, nshards):
    order = sorted(jobs, key=lambda j: -j['natoms'])
    return [j for k, j in enumerate(order) if k % nshards == shard]


def run_one(job, shard, cap, nprocs='4', timeout='10800', tag='p1'):
    jid = job['id']
    cache = os.path.join(HERE, 'caches', f'{tag}_shard{shard}.json')
    env = dict(os.environ,
               DISPATCH_WORK=os.path.join(WS, 'validation', 'repro_runs', tag, jid),
               DISPATCH_CACHE=cache,
               DISCOVERED_CACHE=os.path.join(HERE, 'caches', f'{tag}_disc{shard}.json'),
               NPROCS=nprocs, DFT_TIMEOUT=timeout,
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               DFT_PRERELAX=os.environ.get('DFT_PRERELAX', '0'),
               NEB_GUESS=os.environ.get('NEB_GUESS', '0'),
               DFT_SCAN=os.environ.get('DFT_SCAN', '0'),
               TAUT_2D=os.environ.get('TAUT_2D', '0'),
               XFER_2D=os.environ.get('XFER_2D', '0'))
    log = os.path.join(HERE, 'logs', f'{jid}.log')
    t0 = time.time()
    with open(log, 'w') as f:
        f.write(f'# {jid}  {job["R"]} >> {job["P"]}  kind={job["dkind"]}  '
                f'deposit_ref={job["imag_ref"]} cm-1\n')
        f.flush()
        cmd = [PYBIN, os.path.join(RN, 'validate_candidate.py'),
               '--edge', f'{job["R"]}>>{job["Pfull"]}', '--kind', job['dkind'], '--cap', str(cap)]
        if job.get('force_water'):
            cmd += ['--force-water']
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=RN, env=env)
    dt = time.time() - t0

    got = {}
    if os.path.exists(cache):
        d = json.load(open(cache))
        pf = set(job['Pfull'].split('.'))
        for k, v in d.items():
            if v.get('reactant') == job['R'] and v.get('product') in pf:
                got = v
    res = dict(job, wall_s=round(dt, 1), exit=p.returncode,
               status=got.get('status'), imag_got=got.get('ts_imag_cm-1'),
               imag_all=got.get('ts_imag_all'), n_imag=got.get('n_imag'))
    json.dump(res, open(os.path.join(HERE, 'results', f'{jid}.json'), 'w'), indent=1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shard', type=int, required=True)
    ap.add_argument('--nshards', type=int, required=True)
    ap.add_argument('--cap', type=int, default=3)
    ap.add_argument('--only-kinds', default=None)
    ap.add_argument('--only', default='')
    ap.add_argument('--skip', default='')
    ap.add_argument('--jobs', default='jobs.json')
    ap.add_argument('--nprocs', default='4')
    ap.add_argument('--timeout', default='10800')
    ap.add_argument('--tag', default='p1')
    a = ap.parse_args()

    jobs = json.load(open(os.path.join(HERE, a.jobs)))
    if a.only:
        keep = set(a.only.split(','))
        jobs = [j for j in jobs if j['id'] in keep]
    if a.only_kinds:
        ks = set(a.only_kinds.split(','))
        jobs = [j for j in jobs if j['dkind'] in ks]
    skip = set(x for x in a.skip.split(',') if x)
    jobs = [j for j in jobs if j['id'] not in skip]
    mine = shard_jobs(jobs, a.shard, a.nshards)

    for d in ('logs', 'results', 'caches'):
        os.makedirs(os.path.join(HERE, d), exist_ok=True)
    print(f'shard {a.shard}/{a.nshards}: {len(mine)} jobs -> {[j["id"] for j in mine]}', flush=True)
    for j in mine:
        r = run_one(j, a.shard, a.cap, a.nprocs, a.timeout, a.tag)
        print(f'  {r["id"]:<8} {str(r["status"]):<14} got={r["imag_got"]} ref={r["imag_ref"]} '
              f'({r["wall_s"]/60:.0f} min)', flush=True)
    print(f'shard {a.shard} DONE', flush=True)


if __name__ == '__main__':
    main()
