from pathlib import Path

import duckdb
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell", exc_type=ImportError)
import ifcopenshell.api  # noqa: E402

from ckb.ifc_extract import load  # noqa: E402


def _tiny_model(path: Path) -> None:
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Test")
    ifcopenshell.api.run("unit.assign_unit", f)
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    bldg = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Building")
    ground = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Ground")
    level2 = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 2")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=site, products=[bldg])
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=bldg, products=[ground, level2])
    concrete = ifcopenshell.api.run("material.add_material", f, name="Concrete")
    for storey, n in ((ground, 3), (level2, 2)):
        for i in range(n):
            wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name=f"W{i}")
            ifcopenshell.api.run("spatial.assign_container", f, relating_structure=storey, products=[wall])
            ifcopenshell.api.run("material.assign_material", f, products=[wall], material=concrete)
            qto = ifcopenshell.api.run("pset.add_qto", f, product=wall, name="Qto_WallBaseQuantities")
            ifcopenshell.api.run("pset.edit_qto", f, qto=qto, properties={"NetVolume": 2.5, "Length": 4.0})
    import numpy as np
    m = np.eye(4); m[0, 3], m[1, 3] = 2.5, 1.0             # given in metres; the file stores millimetres
    ifcopenshell.api.run("geometry.edit_object_placement", f, product=wall, matrix=m)
    slab = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSlab", name="S1")
    ifcopenshell.api.run("spatial.assign_container", f, relating_structure=ground, products=[slab])
    f.write(str(path))


def test_ifc_extract_counts_and_quantities(tmp_path):
    model = tmp_path / "tiny.ifc"
    _tiny_model(model)
    con = duckdb.connect()
    info = load(con, model)
    assert info["elements"] == 6 and info["quantities"] == 10
    rows = con.execute("SELECT storey, ifc_class, elements, volume FROM ifc_summary ORDER BY storey, ifc_class").fetchall()
    assert ("Ground", "IfcWall", 3, 7.5) in rows
    assert ("Level 2", "IfcWall", 2, 5.0) in rows
    assert ("Ground", "IfcSlab", 1, None) in rows
    # model lengths are millimetres; stored values are converted to metres
    lengths = con.execute("SELECT DISTINCT value, unit FROM ifc_quantities WHERE quantity = 'Length'").fetchall()
    assert lengths == [(0.004, "m")]
    q = con.execute("SELECT elements, share_with_storey, share_with_material, share_proxy FROM ifc_quality").fetchone()
    assert q == (6, 1.0, round(5 / 6, 3), 0.0)
    assert con.execute("SELECT DISTINCT material FROM ifc_elements WHERE ifc_class='IfcWall'").fetchone()[0] == "Concrete"
    # placements come back in metres (the file stores 2500 mm, 1000 mm)
    placed = con.execute("SELECT x, y, dir_x, dir_y FROM ifc_elements WHERE x IS NOT NULL").fetchall()
    assert placed == [(2.5, 1.0, 1.0, 0.0)]
    # reloading the same model replaces rather than duplicates
    load(con, model)
    assert con.execute("SELECT count(*) FROM ifc_elements").fetchone()[0] == 6
