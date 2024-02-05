# Copyright (c) Tingzheng Hou.
# Distributed under the terms of the MIT License.

"""Utilities for manipulating dictionaries."""

from __future__ import annotations

import math
import re
import string
from typing import TYPE_CHECKING

import numpy as np
from pymatgen.io.lammps.data import CombinedData

from . import MM_of_Elements

if TYPE_CHECKING:
    import pandas as pd
    from MDAnalysis import Universe
    from MDAnalysis.core.groups import AtomGroup, Residue


def mass_to_name(masses: np.ndarray) -> np.ndarray:
    """
    Map atom names to element names.

    Args:
        masses: The masses array of atoms in an ``Universe``.

    Return:
        The element name array.
    """
    names = []
    for mass in masses:
        for item in MM_of_Elements.items():
            if math.isclose(mass, item[1], abs_tol=0.1):
                names.append(item[0])
    assert len(masses) == len(names), "Invalid mass found."
    return np.array(names)


def lmp_mass_to_name(df: pd.DataFrame) -> dict[int, str]:
    """
    Create a dict for mapping atom type id to element from the mass information.

    Args:
        df: The masses attribute from LammpsData object
    Return:
        The element dict.
    """
    atoms = {}
    for row in df.index:
        for item in MM_of_Elements.items():
            if math.isclose(df["mass"][row], item[1], abs_tol=0.01):
                atoms[int(row)] = item[0]
    return atoms


def assign_name(u: Universe, names: np.ndarray):
    """
    Assign resnames to residues in a MDAnalysis.universe object. The function will not overwrite existing names.

    Args:
        u: The universe object to assign resnames to.
        names: The element name array.
    """
    u.add_TopologyAttr("name", values=names)


def assign_resname(u: Universe, res_dict: dict[str, str]):
    """
    Assign resnames to residues in a MDAnalysis.universe object. The function will not overwrite existing resnames.

    Args:
        u: The universe object to assign resnames to.
        res_dict: A dictionary of resnames, where each resname is a key
            and the corresponding values are the selection language.
    """
    u.add_TopologyAttr("resname")
    for key, val in res_dict.items():
        res_group = u.select_atoms(val)
        res_names = res_group.residues.resnames
        res_names[res_names == ""] = key
        res_group.residues.resnames = res_names


def res_dict_from_select_dict(u: Universe, select_dict: dict[str, str]) -> dict[str, str]:
    """
    Infer res_dict (residue selection) from select_dict (atom selection) in a MDAnalysis.universe object.

    Args:
        u: The universe object to assign resnames to.
        select_dict: A dictionary of atom species, where each atom species name is a key
                and the corresponding values are the selection language.

    Return:
        A dictionary of resnames.
    """
    saved_select = []
    res_dict = {}
    for key, val in select_dict.items():
        res_select = "same resid as (" + val + ")"
        res_group = u.select_atoms(res_select)
        if key in ["cation", "anion"] or res_group not in saved_select:
            saved_select.append(res_group)
            res_dict[key] = res_select
    if (
        "cation" in res_dict
        and "anion" in res_dict
        and u.select_atoms(res_dict.get("cation")) == u.select_atoms(res_dict.get("anion"))
    ):
        res_dict.pop("anion")
        res_dict["salt"] = res_dict.pop("cation")
    return res_dict


def res_dict_from_datafile(filename: str) -> dict[str, str]:
    """
    Infer res_dict (residue selection) from a LAMMPS data file.

    Args:
        filename: Path to the data file. The data file must be generated by a CombinedData object.

    Return:
        A dictionary of resnames.
    """
    res_dict = {}
    with open(filename) as f:
        lines = f.readlines()
        if lines[0] == "Generated by pymatgen.io.lammps.data.LammpsData\n" and lines[1].startswith("#"):
            elyte_info = re.findall(r"\w+", lines[1])
            it = iter(elyte_info)
            idx = 1
            for num in it:
                name = next(it)
                if name.isnumeric():
                    frag = int(name)
                    name = next(it)
                    names = [name + c for c in string.ascii_lowercase[0:frag]]
                    start = idx
                    idx += int(num) * frag
                    for i, n in enumerate(names):
                        res_dict[n] = "same mass as resid " + str(start + i)
                else:
                    start = idx
                    idx += int(num)
                    end = idx
                    res_dict[name] = "resid " + str(start) + "-" + str(end - 1)
            return res_dict
        raise ValueError("The LAMMPS data file should be generated by pymatgen.io.lammps.data.")


def res_dict_from_lammpsdata(lammps_data: CombinedData) -> dict[str, str]:
    """
    Infer res_dict (residue selection) from a LAMMPS data file.

    Args:
        lammps_data: A CombinedData object.

    Return:
        A dictionary of resnames.
    """
    assert isinstance(lammps_data, CombinedData)
    idx = 1
    res_dict = {}

    if hasattr(lammps_data, "frags"):
        for name, num, frag in zip(lammps_data.names, lammps_data.nums, lammps_data.frags):
            if frag == 1:
                start = idx
                idx += num
                end = idx
                res_dict[name] = "resid " + str(start) + "-" + str(end - 1)
            else:
                names = [name + c for c in string.ascii_lowercase[0:frag]]
                start = idx
                idx += int(num) * frag
                for i, n in enumerate(names):
                    res_dict[n] = "same mass as resid " + str(start + i)
    else:
        for name, num in zip(lammps_data.names, lammps_data.nums):
            start = idx
            idx += num
            end = idx
            res_dict[name] = "resid " + str(start) + "-" + str(end - 1)
    return res_dict


def select_dict_from_resname(u: Universe) -> dict[str, str]:
    """
    Infer select_dict (possibly interested atom species selection) from resnames in a MDAnalysis.universe object.
    The resname must be pre-assigned already.

    Args:
        u: The universe object to work with.

    Return:
        A dictionary of atom species.
    """
    select_dict: dict[str, str] = {}
    resnames = np.unique(u.residues.resnames)
    for resname in resnames:
        if resname == "":
            continue
        residue = u.select_atoms("resname " + resname).residues[0]
        if np.isclose(residue.charge, 0, atol=1e-5):  # np.sum(residue.atoms.charges)
            if len(residue.atoms.fragments) == 2:
                for i, frag in enumerate(residue.atoms.fragments):
                    charge = np.sum(frag.charges)
                    if charge > 0.001:
                        extract_atom_from_ion(True, frag, select_dict)
                    elif charge < -0.001:
                        extract_atom_from_ion(False, frag, select_dict)
                    else:
                        extract_atom_from_molecule(resname, frag, select_dict, number=i + 1)
            elif len(residue.atoms.fragments) >= 2:
                cation_number = 1
                anion_number = 1
                molecule_number = 1
                for frag in residue.atoms.fragments:
                    charge = np.sum(frag.charges)
                    if charge > 0.001:
                        extract_atom_from_ion(True, frag, select_dict, cation_number)
                        cation_number += 1
                    elif charge < -0.001:
                        extract_atom_from_ion(False, frag, select_dict, anion_number)
                        anion_number += 1
                    else:
                        extract_atom_from_molecule(resname, frag, select_dict, molecule_number)
                        molecule_number += 1
            else:
                extract_atom_from_molecule(resname, residue, select_dict)
        elif residue.charge > 0:
            extract_atom_from_ion(True, residue, select_dict)
        else:
            extract_atom_from_ion(False, residue, select_dict)
    return select_dict


def extract_atom_from_ion(positive: bool, ion: Residue | AtomGroup, select_dict: dict[str, str], number: int = 0):
    """
    Assign the most most charged atom and/or one unique atom in the ion into select_dict.

    Args:
        positive: Whether the charge of ion is positive. Otherwise negative. Default to True.
        ion: Residue or AtomGroup
        select_dict: A dictionary of atom species, where each atom species name is a key
            and the corresponding values are the selection language.
        number: The serial number of the ion.
    """
    if positive:
        cation_name = "cation" if number == 0 else "cation_" + str(number)
        if len(ion.atoms.types) == 1:
            select_dict[cation_name] = "type " + ion.atoms.types[0]
        else:
            # The most positively charged atom in the cation
            pos_center = ion.atoms[np.argmax(ion.atoms.charges)]
            unique_types = np.unique(ion.atoms.types, return_counts=True)
            # One unique atom in the cation
            uni_center = unique_types[0][np.argmin(unique_types[1])]
            if pos_center.type == uni_center:
                select_dict[cation_name] = "type " + uni_center
            else:
                select_dict[cation_name + "_" + pos_center.name + pos_center.type] = "type " + pos_center.type
                select_dict[cation_name] = "type " + uni_center
    else:
        anion_name = "anion" if number == 0 else "anion_" + str(number)
        if len(ion.atoms.types) == 1:
            select_dict[anion_name] = "type " + ion.atoms.types[0]
        else:
            # The most negatively charged atom in the anion
            neg_center = ion.atoms[np.argmin(ion.atoms.charges)]
            unique_types = np.unique(ion.atoms.types, return_counts=True)
            # One unique atom in the anion
            uni_center = unique_types[0][np.argmin(unique_types[1])]
            if neg_center.type == uni_center:
                select_dict[anion_name] = "type " + uni_center
            else:
                select_dict[anion_name + "_" + neg_center.name + neg_center.type] = "type " + neg_center.type
                select_dict[anion_name] = "type " + uni_center


def extract_atom_from_molecule(
    resname: str, molecule: Residue | AtomGroup, select_dict: dict[str, str], number: int = 0
):
    """
    Assign the most negatively charged atom in the molecule into select_dict.

    Args:
        resname: The name of the molecule
        molecule: The Residue or AtomGroup obj of the molecule.
        select_dict: A dictionary of atom species, where each atom species name is a key
            and the corresponding values are the selection language.
        number: The serial number of the molecule under the name of resname.
    """
    # neg_center = residue.atoms[np.argmin(residue.atoms.charges)]
    # select_dict[resname + "-" + neg_center.name + neg_center.type] = "type " + neg_center.type
    # pos_center = residue.atoms[np.argmax(residue.atoms.charges)]
    # select_dict[resname + "+" + pos_center.name + pos_center.type] = "type " + pos_center.type

    # The most negatively charged atom in the anion
    if number > 0:
        resname = resname + "_" + str(number)
    neg_center = molecule.atoms[np.argmin(molecule.atoms.charges)]
    select_dict[resname] = "type " + neg_center.type
