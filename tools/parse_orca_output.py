"""Shim so skills can call: python tools/parse_orca_output.py ..."""
import runpy
import os
runpy.run_path(os.path.join(os.path.dirname(__file__), "geometry", "parse_orca_output.py"), run_name="__main__")
