#!/usr/bin/env python3
"""Remove stereochemistry from SMILES or XYZ file and output canonical SMILES."""

import sys
from pathlib import Path
from rdkit import Chem
from rdkit.Chem import AllChem, rdDetermineBonds


def read_xyz_to_mol(xyz_path: str) -> Chem.Mol | None:
    """Read an XYZ file and convert to RDKit Mol object with connectivity."""
    try:
        mol = Chem.MolFromXYZFile(xyz_path)
        if mol is None:
            return None
        rdDetermineBonds.DetermineConnectivity(mol)
        try:
            rdDetermineBonds.DetermineBondOrders(mol)
        except ValueError:
            # If bond order determination fails, use connectivity only
            pass
        return mol
    except Exception:
        return None


def remove_stereo_from_smiles(smiles: str) -> str:
    """Remove stereochemistry from SMILES string."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    Chem.RemoveStereochemistry(mol)
    return Chem.MolToSmiles(mol)


def remove_stereo_from_xyz(xyz_path: str) -> str | None:
    """Remove stereochemistry from XYZ file and return canonical SMILES."""
    try:
        mol = read_xyz_to_mol(xyz_path)
        if mol is None:
            return None
        # Remove explicit hydrogens for cleaner SMILES output
        try:
            mol = Chem.RemoveHs(mol)
        except Exception:
            # If removing Hs fails, continue with explicit Hs
            pass
        # Sanitize to fix valences and aromaticity
        try:
            Chem.SanitizeMol(mol)
        except Exception:
            # If sanitization fails, try to get SMILES anyway
            pass
        Chem.RemoveStereochemistry(mol)
        return Chem.MolToSmiles(mol)
    except Exception:
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_arg = sys.argv[1]
    else:
        input_arg = input("Enter SMILES or XYZ file path: ").strip()

    # Check if input is a file path
    if Path(input_arg).exists() and input_arg.endswith('.xyz'):
        result = remove_stereo_from_xyz(input_arg)
    else:
        result = remove_stereo_from_smiles(input_arg)

    print(result)
