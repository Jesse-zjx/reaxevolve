"""Shim so skills can call: python tools/map_reaction_atoms.py ..."""
import runpy
import os
runpy.run_path(os.path.join(os.path.dirname(__file__), "geometry", "map_reaction_atoms.py"), run_name="__main__")
