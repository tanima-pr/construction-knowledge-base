"""Pull building elements and their quantities out of an IFC (BIM) model into DuckDB.

Tables:
  ifc_elements(model, global_id, ifc_class, name, storey, type_name, material)
  ifc_quantities(model, global_id, ifc_class, qto_set, quantity, value, unit_kind, unit)
Views:
  ifc_summary - element counts and summed quantities (m, m2, m3) by storey and class
  ifc_quality - per model: share of elements with a storey, material and quantities; share of proxies

Units: IFC models declare their own units, often millimetres for length but m2/m3 for area and
volume. Every quantity is converted to SI (m, m2, m3, kg) on load so models can be compared and summed.
"""
from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as eu
import ifcopenshell.util.unit as uu

# IFC quantity class -> (value attribute, kind, IFC unit type for scaling, SI unit label)
QTY_ATTRS = {
    "IfcQuantityLength": ("LengthValue", "length", "LENGTHUNIT", "m"),
    "IfcQuantityArea": ("AreaValue", "area", "AREAUNIT", "m2"),
    "IfcQuantityVolume": ("VolumeValue", "volume", "VOLUMEUNIT", "m3"),
    "IfcQuantityCount": ("CountValue", "count", None, "count"),
    "IfcQuantityWeight": ("WeightValue", "weight", "MASSUNIT", "kg"),
}

DDL = """
CREATE TABLE IF NOT EXISTS ifc_elements (model VARCHAR, global_id VARCHAR, ifc_class VARCHAR, name VARCHAR,
    storey VARCHAR, type_name VARCHAR, material VARCHAR);
CREATE TABLE IF NOT EXISTS ifc_quantities (model VARCHAR, global_id VARCHAR, ifc_class VARCHAR, qto_set VARCHAR,
    quantity VARCHAR, value DOUBLE, unit_kind VARCHAR, unit VARCHAR);
CREATE OR REPLACE VIEW ifc_summary AS
SELECT e.model, coalesce(e.storey, '(no storey)') AS storey, e.ifc_class, count(*) AS elements,
       sum(q.area) AS area, sum(q.volume) AS volume, sum(q.length) AS length
FROM ifc_elements e
LEFT JOIN (
    SELECT global_id,
           -- one measure per column: surface area (not beam cross-sections), net volume, run length
           -- (not width/depth/thickness), so different measures are never summed together
           max(value) FILTER (WHERE unit_kind = 'area' AND quantity IN ('NetSideArea', 'NetArea', 'GrossSideArea', 'GrossArea')) AS area,
           max(value) FILTER (WHERE unit_kind = 'volume' AND quantity IN ('NetVolume', 'GrossVolume')) AS volume,
           max(value) FILTER (WHERE unit_kind = 'length' AND quantity = 'Length') AS length
    FROM ifc_quantities GROUP BY global_id) q USING (global_id)
GROUP BY ALL ORDER BY model, storey, ifc_class;
CREATE OR REPLACE VIEW ifc_quality AS
SELECT e.model, count(*) AS elements,
       round(avg(CASE WHEN e.storey IS NOT NULL THEN 1 ELSE 0 END), 3) AS share_with_storey,
       round(avg(CASE WHEN e.material IS NOT NULL THEN 1 ELSE 0 END), 3) AS share_with_material,
       round(avg(CASE WHEN q.global_id IS NOT NULL THEN 1 ELSE 0 END), 3) AS share_with_quantities,
       round(avg(CASE WHEN e.ifc_class = 'IfcBuildingElementProxy' THEN 1 ELSE 0 END), 3) AS share_proxy
FROM ifc_elements e
LEFT JOIN (SELECT DISTINCT global_id FROM ifc_quantities) q USING (global_id)
GROUP BY e.model ORDER BY e.model;
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
    scale = {t: uu.calculate_unit_scale(f, t) for t in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT", "MASSUNIT")}
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
                spec = QTY_ATTRS.get(q.is_a())
                if spec:
                    attr, kind, unit_type, si = spec
                    value = float(getattr(q, attr)) * (scale[unit_type] if unit_type else 1.0)
                    quantities.append((model_name, el.GlobalId, el.is_a(), pdef.Name, q.Name,
                                       round(value, 6), kind, si))
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
        con.executemany("INSERT INTO ifc_quantities VALUES (?,?,?,?,?,?,?,?)", quantities)
    return {"model": model, "elements": len(elements), "quantities": len(quantities)}
