"""Shim so skills can call: python tools/inquire.py ..."""
import runpy
import os
runpy.run_path(os.path.join(os.path.dirname(__file__), "geometry", "inquire.py"), run_name="__main__")
