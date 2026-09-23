from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION


REQUIRED_TOP_LEVEL = (
    "software_version", "schema_version", "analysis_type", "variable",
    "period", "observation_coverage", "depth_information", "source_file",
    "source_units", "output_units", "unit_conversion", "processing",
    "integrity", "outputs",
)

REQUIRED_PROCESSING = (
    "spatial_weighting", "native_grid_preserved", "regridding",
    "vertical_interpolation", "interpolation", "extrapolation",
    "gap_filling", "autocorrelation_correction", "unit_conversion",
    "source_units", "output_units",
)

def validate_report(report: Mapping[str, Any], require_output_files: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in report:
            errors.append(f"missing_top_level:{key}")

    period = report.get("period")
    if not isinstance(period, Mapping) or not period.get("start") or not period.get("end"):
        errors.append("invalid_period")

    processing = report.get("processing")
    if not isinstance(processing, Mapping):
        errors.append("invalid_processing")
    else:
        for key in REQUIRED_PROCESSING:
            if key not in processing:
                errors.append(f"missing_processing:{key}")
        if processing.get("native_grid_preserved") is not True:
            errors.append("native_grid_not_preserved")
        for flag in ("regridding", "vertical_interpolation", "interpolation", "extrapolation", "gap_filling"):
            if processing.get(flag) is not False:
                errors.append(f"processing_flag_not_false:{flag}")

    integrity = report.get("integrity")
    if not isinstance(integrity, Mapping):
        errors.append("invalid_integrity")
    else:
        status = integrity.get("status")
        if status not in {"PASS", "WARN", "FAIL"}:
            errors.append("invalid_integrity_status")
        if "finite_series_values" in integrity and "missing_series_values" in integrity:
            finite = integrity.get("finite_series_values")
            missing = integrity.get("missing_series_values")
            if isinstance(finite, (int, float)) and isinstance(missing, (int, float)) and finite < 0:
                errors.append("negative_finite_count")
            if isinstance(missing, (int, float)) and missing < 0:
                errors.append("negative_missing_count")

    outputs = report.get("outputs")
    if not isinstance(outputs, Mapping) or not outputs:
        errors.append("invalid_outputs")
    elif require_output_files:
        for key, value in outputs.items():
            if value and isinstance(value, str) and not Path(value).exists():
                warnings.append(f"output_not_found:{key}")

    depth = report.get("depth_information")
    if not isinstance(depth, Mapping):
        errors.append("invalid_depth_information")

    version = report.get("software_version")
    schema = report.get("schema_version")
    if version != SOFTWARE_VERSION:
        warnings.append(f"software_version:{version}")
    if schema != REPORT_SCHEMA_VERSION:
        warnings.append(f"schema_version:{schema}")

    return {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "required_keys_checked": len(REQUIRED_TOP_LEVEL),
        "processing_flags_checked": 5,
    }
