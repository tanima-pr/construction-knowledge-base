"""Pull building elements and their quantities out of an IFC (BIM) model into DuckDB.

Tables:
  ifc_elements(model, global_id, ifc_class, name, storey, type_name, material)
  ifc_quantities(model, global_id, ifc_class, qto_set, quantity, value, unit_kind)
View:
  ifc_summary - element counts and summed quantities by storey and class
"""
from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as eu

QTY_ATTRS = {
    "IfcQuantityLength": ("LengthValue", "length"),
    "IfcQuantityArea": ("AreaValue", "area"),
    "IfcQuantityVolume": ("VolumeValue", "volume"),
    "IfcQuantityCount": ("CountValue", "count"),
    "IfcQuantityWeight": ("WeightValue", "weight"),
}

DDL = """
CREATE TABLE IF NOT EXISTS ifc_elements (model VARCHAR, global_id VARCHAR, ifc_class VARCHAR, name VARCHAR,
    storey VARCHAR, type_name VARCHAR, material VARCHAR);
CREATE TABLE IF NOT EXISTS ifc_quantities (model VARCHAR, global_id VARCHAR, ifc_class VARCHAR, qto_set VARCHAR,
    quantity VARCHAR, value DOUBLE, unit_kind VARCHAR);
CREATE OR REPLACE VIEW ifc_summary AS
SELECT e.model, coalesce(e.storey, '(no storey)') AS storey, e.ifc_class, count(*) AS elements,
       sum(q.area) AS area, sum(q.volume) AS volume, sum(q.length) AS length
FROM ifc_elements e
LEFT JOIN (
    SELECT global_id,
           max(value) FILTER (WHERE unit_kind = 'area')   AS area,
           max(value) FILTER (WHERE unit_kind = 'volume') AS volume,
           max(value) FILTER (WHERE unit_kind = 'length') AS length
    FROM ifc_quantities GROUP BY global_id) q USING (global_id)
GROUP BY ALL ORDER BY model, storey, ifc_class;
"""


def _material(el) -> str | None:
    mat = eu.get_material(el, should_skip_usage=True)
    if mat is None:
        return None
    if mat.is_a("IfcMaterial"):
        return mat.Name
    if mat.is_a("IfcMaterialLayerSet"):
        return " / ".join(l.Material.Name for l in mat.MaterialLayers if l.Material)
    return getattr(mat, "Name", None) or mat.is_a()


def extract(ifc_path: Path) -> tuple[list[tuple], list[tuple]]:
    model_name = ifc_path.stem
    f = ifcopenshell.open(str(ifc_path))
    elements, quantities = [], []
    for el in f.by_type("IfcElement"):
        if el.is_a("IfcOpeningElement") or el.is_a("IfcFeatureElement"):
            continue
        storey = eu.get_container(el)
        etype = eu.get_type(el)
        elements.append((model_name, el.GlobalId, el.is_a(), el.Name,
                         storey.Name if storey else None, etype.Name if etype else None, _material(el)))
        for rel in getattr(el, "IsDefinedBy", []) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pdef = rel.RelatingPropertyDefinition
            if not pdef.is_a("IfcElementQuantity"):
                continue
            for q in pdef.Quantities:
                attr = QTY_ATTRS.get(q.is_a())
                if attr:
                    quantities.append((model_name, el.GlobalId, el.is_a(), pdef.Name, q.Name,
                                       float(getattr(q, attr[0])), attr[1]))
    return elements, quantities


def load(con, ifc_path: Path) -> dict:
    con.execute(DDL)
    elements, quantities = extract(ifc_path)
    model = ifc_path.stem
    con.execute("DELETE FROM ifc_elements WHERE model = ?", [model])
    con.execute("DELETE FROM ifc_quantities WHERE model = ?", [model])
    if elements:
        con.executemany("INSERT INTO ifc_elements VALUES (?,?,?,?,?,?,?)", elements)
    if quantities:
        con.executemany("INSERT INTO ifc_quantities VALUES (?,?,?,?,?,?,?)", quantities)
    return {"model": model, "elements": len(elements), "quantities": len(quantities)}
