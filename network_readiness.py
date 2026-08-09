from __future__ import annotations

import argparse
import html
import ipaddress
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "bestethernet.network-readiness.v1"


class ReadinessError(ValueError):
    pass


def load_job(path: Path) -> dict[str, Any]:
    job = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "job_id",
        "venue_id",
        "test_window",
        "candidate_interfaces",
        "required_samples",
        "thresholds",
        "hotspot_required",
        "report_output",
    }
    missing = sorted(required - job.keys())
    if missing:
        raise ReadinessError("missing job fields: " + ", ".join(missing))
    if job["schema_version"] != SCHEMA_VERSION:
        raise ReadinessError(f"unsupported schema_version: {job['schema_version']}")
    if not isinstance(job["job_id"], str) or not job["job_id"].strip():
        raise ReadinessError("job_id must be a non-empty string")
    if not isinstance(job["candidate_interfaces"], list) or not job["candidate_interfaces"]:
        raise ReadinessError("candidate_interfaces must be a non-empty list")
    if len(set(job["candidate_interfaces"])) != len(job["candidate_interfaces"]):
        raise ReadinessError("candidate_interfaces must be unique")
    required_samples = job["required_samples"]
    if not isinstance(required_samples, int) or required_samples < 3:
        raise ReadinessError("required_samples must be an integer >= 3")
    thresholds = job["thresholds"]
    for key in ("max_latency_ms", "min_download_mbps", "min_upload_mbps"):
        if key not in thresholds or not isinstance(thresholds[key], (int, float)):
            raise ReadinessError(f"thresholds.{key} must be numeric")
        if thresholds[key] < 0:
            raise ReadinessError(f"thresholds.{key} must be >= 0")
    return job


def load_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReadinessError(f"invalid JSONL at line {line_number}: {exc}") from exc
        if not isinstance(item, dict):
            raise ReadinessError(f"JSONL line {line_number} must be an object")
        samples.append(item)
    return samples


def mask_ip(value: str | None) -> str | None:
    if not value:
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "[invalid-ip]"
    if address.version == 4:
        parts = value.split(".")
        return ".".join(parts[:3] + ["x"])
    network = ipaddress.ip_network(f"{address}/64", strict=False)
    return f"{network.network_address}/64"


def _valid_metric_sample(item: dict[str, Any], interface: str, job_id: str) -> tuple[bool, str]:
    if item.get("job_id") != job_id:
        return False, "JOB_ID_MISMATCH"
    if item.get("requested_interface") != interface:
        return False, "OTHER_INTERFACE"
    if not item.get("success"):
        return False, "MEASUREMENT_FAILED"
    if item.get("actual_interface") != interface:
        return False, "EGRESS_MISMATCH"
    for field in ("latency_ms", "download_mbps", "upload_mbps"):
        value = item.get(field)
        if not isinstance(value, (int, float)) or value < 0:
            return False, f"INVALID_{field.upper()}"
    return True, "VALID"


def summarize_interface(
    interface: str,
    samples: list[dict[str, Any]],
    *,
    job_id: str,
    required_samples: int,
    thresholds: dict[str, float],
    public: bool,
) -> dict[str, Any]:
    requested = [
        item
        for item in samples
        if item.get("job_id") == job_id and item.get("requested_interface") == interface
    ]
    valid: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = defaultdict(int)
    for item in requested:
        ok, reason = _valid_metric_sample(item, interface, job_id)
        if ok:
            valid.append(item)
        else:
            rejection_counts[reason] += 1

    summary: dict[str, Any] = {
        "interface": interface,
        "sample_count": len(requested),
        "successful_sample_count": len(valid),
        "required_samples": required_samples,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "aggregation": "median for latency/download/upload; minimum for download/upload",
        "status": "INSUFFICIENT_EVIDENCE",
        "thresholds_met": False,
        "reason_codes": [],
        "source_ips": sorted(
            {
                mask_ip(item.get("source_ip")) if public else item.get("source_ip")
                for item in requested
                if item.get("source_ip")
            }
        ),
        "gateways": sorted(
            {
                mask_ip(item.get("gateway")) if public else item.get("gateway")
                for item in requested
                if item.get("gateway")
            }
        ),
    }
    if len(valid) < required_samples:
        summary["reason_codes"].append("REQUIRED_SAMPLE_COUNT_NOT_MET")
        if rejection_counts.get("EGRESS_MISMATCH"):
            summary["reason_codes"].append("EGRESS_MISMATCH_REJECTED")
        return summary

    latencies = [float(item["latency_ms"]) for item in valid]
    downloads = [float(item["download_mbps"]) for item in valid]
    uploads = [float(item["upload_mbps"]) for item in valid]
    summary.update(
        {
            "latency_median_ms": round(statistics.median(latencies), 3),
            "download_median_mbps": round(statistics.median(downloads), 3),
            "download_min_mbps": round(min(downloads), 3),
            "upload_median_mbps": round(statistics.median(uploads), 3),
            "upload_min_mbps": round(min(uploads), 3),
        }
    )
    checks = {
        "latency": summary["latency_median_ms"] <= thresholds["max_latency_ms"],
        "download": summary["download_min_mbps"] >= thresholds["min_download_mbps"],
        "upload": summary["upload_min_mbps"] >= thresholds["min_upload_mbps"],
    }
    summary["threshold_checks"] = checks
    summary["thresholds_met"] = all(checks.values())
    summary["status"] = "MEETS_CONFIGURED_THRESHOLDS" if summary["thresholds_met"] else "BELOW_CONFIGURED_THRESHOLDS"
    summary["reason_codes"] = (
        ["CONFIGURED_THRESHOLDS_MET"]
        if summary["thresholds_met"]
        else [f"{name.upper()}_THRESHOLD_NOT_MET" for name, passed in checks.items() if not passed]
    )
    return summary


def build_report(job: dict[str, Any], samples: list[dict[str, Any]], *, public: bool) -> dict[str, Any]:
    summaries = [
        summarize_interface(
            interface,
            samples,
            job_id=job["job_id"],
            required_samples=job["required_samples"],
            thresholds=job["thresholds"],
            public=public,
        )
        for interface in job["candidate_interfaces"]
    ]
    eligible = [s for s in summaries if s["status"] == "MEETS_CONFIGURED_THRESHOLDS"]
    eligible.sort(
        key=lambda s: (
            s["latency_median_ms"],
            -s["download_min_mbps"],
            -s["upload_min_mbps"],
            s["interface"],
        )
    )
    primary = eligible[0] if eligible else None
    fallback = eligible[1] if len(eligible) > 1 else None
    report_status = "READY_FOR_HUMAN_REVIEW" if primary else "INSUFFICIENT_EVIDENCE"
    selection = {
        "status": report_status,
        "primary_interface": primary["interface"] if primary else None,
        "fallback_interface": fallback["interface"] if fallback else None,
        "selection_method": (
            "Only candidates with >= required samples and all configured thresholds met are eligible; "
            "eligible candidates rank by latency median ascending, then download/upload minimum descending."
        ),
        "reason_codes": (
            ["PRIMARY_SELECTED_FROM_THRESHOLD_ELIGIBLE_CANDIDATES"]
            if primary
            else ["NO_CANDIDATE_WITH_SUFFICIENT_EVIDENCE_AND_THRESHOLDS"]
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job["job_id"],
        "venue_id": job["venue_id"],
        "test_window": job["test_window"],
        "hotspot_required": bool(job["hotspot_required"]),
        "public_report": public,
        "thresholds": job["thresholds"],
        "candidate_summaries": summaries,
        "selection": selection,
        "disclaimer": (
            "Configured thresholds are an operator-defined screening rule, not a guarantee of VR, "
            "VRChat, HMD, venue Wi-Fi, or event quality."
        ),
        "source_log_contract": "measurements.jsonl rows must carry the same job_id as this report",
    }


def render_html(report: dict[str, Any]) -> str:
    rows = []
    for item in report["candidate_summaries"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['interface'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{item['successful_sample_count']}/{item['required_samples']}</td>"
            f"<td>{item.get('latency_median_ms', '—')}</td>"
            f"<td>{item.get('download_median_mbps', '—')} / {item.get('download_min_mbps', '—')}</td>"
            f"<td>{item.get('upload_median_mbps', '—')} / {item.get('upload_min_mbps', '—')}</td>"
            "</tr>"
        )
    primary = report["selection"]["primary_interface"] or "なし"
    fallback = report["selection"]["fallback_interface"] or "なし"
    return f"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<title>Network Readiness Report {html.escape(report['job_id'])}</title>
<body>
<h1>Network Readiness Report</h1>
<dl>
<dt>Job ID</dt><dd>{html.escape(report['job_id'])}</dd>
<dt>Venue ID</dt><dd>{html.escape(report['venue_id'])}</dd>
<dt>判定</dt><dd>{html.escape(report['selection']['status'])}</dd>
<dt>Primary</dt><dd>{html.escape(primary)}</dd>
<dt>Fallback</dt><dd>{html.escape(fallback)}</dd>
</dl>
<table>
<thead><tr><th>Interface</th><th>Status</th><th>Valid samples</th><th>Latency median ms</th><th>Download median/min Mbps</th><th>Upload median/min Mbps</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<p>{html.escape(report['selection']['selection_method'])}</p>
<p><strong>重要:</strong> {html.escape(report['disclaimer'])}</p>
</body>
</html>
"""


def write_report(job: dict[str, Any], report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "network-readiness.json"
    html_path = output_dir / "network-readiness.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return json_path, html_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed network readiness report")
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--public", action="store_true", help="Mask source IP and gateway values")
    args = parser.parse_args(argv)

    job = load_job(args.job)
    report = build_report(job, load_samples(args.samples), public=args.public)
    write_report(job, report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
