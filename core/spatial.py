from pathlib import Path
import geopandas as gpd

def inspect_shapefile(path):
    path = Path(path)
    if path.suffix.lower() != ".shp":
        raise ValueError("The selected file must have a .shp extension.")

    # GeoPandas/Fiona will automatically use the companion .shx/.dbf/.prj files.
    gdf = gpd.read_file(path)

    if gdf.empty:
        raise ValueError("The Shapefile contains no features.")
    if gdf.crs is None:
        raise ValueError("The Shapefile has no CRS definition (.prj).")

    if not gdf.geometry.is_valid.all():
        gdf = gdf.copy()
        gdf.geometry = gdf.geometry.make_valid()

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    bounds = gdf.total_bounds
    return {
        "crs": "EPSG:4326",
        "geometry": ", ".join(sorted(set(gdf.geometry.geom_type))),
        "features": len(gdf),
        "xmin": float(bounds[0]),
        "ymin": float(bounds[1]),
        "xmax": float(bounds[2]),
        "ymax": float(bounds[3]),
    }
