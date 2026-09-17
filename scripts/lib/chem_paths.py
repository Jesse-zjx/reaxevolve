"""Package-local paths for reaxevolve. Override with CHEM_* / ORCA_DIR / XTB_BIN."""
import os
import sys

LIB = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(LIB)
PACKAGE = os.path.dirname(SCRIPTS)

TOOLS = os.path.join(PACKAGE, "tools")
# Genesis has no legacy qm-workspace; ROOT points at runs/ for scratch.
ROOT = os.environ.get("CHEM_WS", os.path.join(PACKAGE, "runs"))
RN = os.environ.get("CHEM_RN", os.path.join(PACKAGE, "graph", "canonical"))
RESOURCES = os.path.join(ROOT, "resources")

_GRAPH_CANON = os.path.join(PACKAGE, "graph", "canonical")
GRAPH = os.environ.get("CHEM_GRAPH", _GRAPH_CANON)
GRAPH_ROOT = os.environ.get("CHEM_GRAPH_ROOT", os.path.join(PACKAGE, "graph"))
DEPOSITS = os.environ.get("CHEM_DEPOSITS", os.path.join(PACKAGE, "deposits"))
RUNS = os.environ.get("CHEM_RUNS", os.path.join(PACKAGE, "runs"))
VALIDATION = os.environ.get("CHEM_VALIDATION", os.path.join(RUNS, "validation"))
POLICY = os.path.join(PACKAGE, "policy")
EVOLUTION = os.path.join(PACKAGE, "evolution")
LOOP = os.path.join(PACKAGE, "loop")
SKILLS = os.path.join(PACKAGE, ".skills")

ORCA_DIR = os.environ.get(
    "ORCA_DIR", "/root/orca_6_1_1_linux_x86-64_shared_openmpi418_nodmrg"
)
XTB_BIN = os.environ.get("XTB_BIN", "/root/xtb/xtb-dist/bin/xtb")
PYBIN = os.environ.get(
    "CHEM_PYTHON", sys.executable or "/root/miniforge3/envs/harness/bin/python3"
)
XTB_DIR = os.path.dirname(XTB_BIN)


def orca_env(**extra):
    env = dict(
        os.environ,
        PATH=XTB_DIR + ":" + ORCA_DIR + ":" + os.environ.get("PATH", ""),
        LD_LIBRARY_PATH=ORCA_DIR + ":" + os.environ.get("LD_LIBRARY_PATH", ""),
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        OMP_STACKSIZE="4G",
    )
    env.update({k: str(v) for k, v in extra.items()})
    return env


def bootstrap():
    for p in (
        RESOURCES,
        RN,
        GRAPH,
        GRAPH_ROOT,
        os.path.join(GRAPH_ROOT, "caches"),
        os.path.join(GRAPH_ROOT, "derived"),
        DEPOSITS,
        RUNS,
        VALIDATION,
        EVOLUTION,
        os.path.join(EVOLUTION, "snapshots"),
        os.path.join(PACKAGE, "evidence", "memory", "experience"),
        os.path.join(PACKAGE, "evidence", "state"),
        os.path.join(PACKAGE, "evidence", "audit"),
        os.path.join(PACKAGE, "evidence", "archive"),
        os.path.join(PACKAGE, "evidence", "state", "loop"),
    ):
        os.makedirs(p, exist_ok=True)
    return PACKAGE
