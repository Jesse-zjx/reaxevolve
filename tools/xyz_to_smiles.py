"""Shim so skills can call: python tools/xyz_to_smiles.py ..."""
import runpy
import os
runpy.run_path(os.path.join(os.path.dirname(__file__), "geometry", "xyz_to_smiles.py"), run_name="__main__")
