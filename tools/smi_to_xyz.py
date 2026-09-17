"""Shim so skills can call: python tools/smi_to_xyz.py ..."""
import runpy
import os
runpy.run_path(os.path.join(os.path.dirname(__file__), "geometry", "smi_to_xyz.py"), run_name="__main__")
