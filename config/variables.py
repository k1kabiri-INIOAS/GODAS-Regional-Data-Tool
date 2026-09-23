"""Central metadata catalog for the monthly GODAS datasets exposed by NOAA PSL.

The catalog mirrors the primary monthly GODAS model-output files currently exposed in
NOAA PSL's GODAS directory.  Variable metadata is intentionally centralized so that
download, QC, standardization, analysis, trend and spatial-visualization modules use
the same definitions.
"""

GODAS_VARIABLES = {
    "temperature": {
        "label": "Potential Temperature",
        "dataset": "pottmp",
        "units": "K",
        "dimensions": "time, depth, lat, lon",
        "has_depth": True,
        "group": "3D Ocean State",
        "unit_options": [("Native GODAS units", "native"), ("°C", "celsius")],
    },
    "salinity": {
        "label": "Salinity",
        "dataset": "salt",
        "units": "kg kg-1",
        "dimensions": "time, depth, lat, lon",
        "has_depth": True,
        "group": "3D Ocean State",
        "unit_options": [("Native GODAS units", "native"), ("PSU (approx.)", "psu_approx")],
    },
    "u_current": {
        "label": "Zonal Current (U)",
        "dataset": "ucur",
        "units": "m s-1",
        "dimensions": "time, depth, lat, lon",
        "has_depth": True,
        "group": "3D Ocean State",
        "unit_options": [("Native GODAS units", "native")],
    },
    "v_current": {
        "label": "Meridional Current (V)",
        "dataset": "vcur",
        "units": "m s-1",
        "dimensions": "time, depth, lat, lon",
        "has_depth": True,
        "group": "3D Ocean State",
        "unit_options": [("Native GODAS units", "native")],
    },
    "vertical_velocity": {
        "label": "Geometric Vertical Velocity",
        "dataset": "dzdt",
        "units": "m s-1",
        "dimensions": "time, depth, lat, lon",
        "has_depth": True,
        "group": "3D Ocean Dynamics",
        "unit_options": [("Native GODAS units", "native")],
    },
    "mld": {
        "label": "Mixed Layer Depth",
        "dataset": "dbss_obml",
        "units": "m",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface / Depth Metrics",
        "unit_options": [("Native GODAS units", "native")],
    },
    "isothermal_layer_depth": {
        "label": "Isothermal Layer Depth",
        "dataset": "dbss_obil",
        "units": "m",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface / Depth Metrics",
        "unit_options": [("Native GODAS units", "native")],
    },
    "sea_surface_height": {
        "label": "Sea Surface Height",
        "dataset": "sshg",
        "units": "m",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface Fluxes / Height",
        "unit_options": [("Native GODAS units", "native")],
    },
    "surface_heat_flux": {
        "label": "Total Downward Heat Flux",
        "dataset": "thflx",
        "units": "W m-2",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface Fluxes / Height",
        "unit_options": [("Native GODAS units", "native")],
    },
    "surface_salt_flux": {
        "label": "Surface Salt Flux",
        "dataset": "sltfl",
        "units": "g cm-2 s-1",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface Fluxes / Height",
        "unit_options": [("Native GODAS units", "native")],
    },
    "u_momentum_flux": {
        "label": "Zonal Momentum Flux (U)",
        "dataset": "uflx",
        "units": "N m-2",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface Fluxes / Height",
        "unit_options": [("Native GODAS units", "native")],
    },
    "v_momentum_flux": {
        "label": "Meridional Momentum Flux (V)",
        "dataset": "vflx",
        "units": "N m-2",
        "dimensions": "time, lat, lon",
        "has_depth": False,
        "group": "Surface Fluxes / Height",
        "unit_options": [("Native GODAS units", "native")],
    },
}


def variable_tuple_catalog():
    """Return the compact tuple mapping used by legacy modules."""
    return {
        key: (meta["dataset"], meta["label"], meta["units"], bool(meta["has_depth"]))
        for key, meta in GODAS_VARIABLES.items()
    }
