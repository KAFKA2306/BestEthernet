import json
import tempfile
import unittest
from pathlib import Path

from network_readiness import SCHEMA_VERSION, build_report, load_job, mask_ip, render_html


def job():
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": "venue-demo-001",
        "venue_id": "demo-venue",
        "test_window": "2026-08-09T00:00:00Z/2026-08-09T01:00:00Z",
        "candidate_interfaces": ["Ethernet A", "Ethernet B"],
        "required_samples": 3,
        "thresholds": {
            "max_latency_ms": 30.0,
            "min_download_mbps": 50.0,
            "min_upload_mbps": 10.0,
        },
        "hotspot_required": True,
        "report_output": "reports/demo",
    }


def sample(interface, *, latency=10, down=100, up=20, success=True, actual=None, job_id="venue-demo-001"):
    return {
        "requested_interface": interface,
        "actual_interface": actual if actual is not None else interface,
        "source_ip": "192.0.2.44",
        "gateway": "192.0.2.1",
        "measurement_server": "fixture/server",
        "timestamp_utc": "2026-08-09T00:00:00+00:00",
        "duration_seconds": 1.0,
        "sample_count": 1 if success else 0,
        "latency_ms": latency if success else None,
        "download_mbps": down if success else None,
        "upload_mbps": up if success else None,
        "success": success,
        "failure_reason": None if success else "fixture failure",
        "job_id": job_id,
    }


class ReadinessReportTests(unittest.TestCase):
    def test_three_samples_produce_median_minimum_and_primary(self):
        samples = [
            sample("Ethernet A", latency=9, down=90, up=19),
            sample("Ethernet A", latency=11, down=100, up=21),
            sample("Ethernet A", latency=10, down=95, up=20),
            sample("Ethernet B", latency=20, down=70, up=15),
            sample("Ethernet B", latency=22, down=80, up=16),
            sample("Ethernet B", latency=21, down=75, up=17),
        ]
        report = build_report(job(), samples, public=False)
        first = report["candidate_summaries"][0]
        self.assertEqual(first["latency_median_ms"], 10.0)
        self.assertEqual(first["download_median_mbps"], 95.0)
        self.assertEqual(first["download_min_mbps"], 90.0)
        self.assertEqual(first["upload_median_mbps"], 20.0)
        self.assertEqual(first["upload_min_mbps"], 19.0)
        self.assertEqual(report["selection"]["primary_interface"], "Ethernet A")
        self.assertEqual(report["selection"]["fallback_interface"], "Ethernet B")
        self.assertEqual(report["selection"]["status"], "READY_FOR_HUMAN_REVIEW")

    def test_egress_mismatch_is_rejected_and_cannot_satisfy_sample_gate(self):
        samples = [sample("Ethernet A"), sample("Ethernet A"), sample("Ethernet A", actual="Ethernet B")]
        report = build_report(job(), samples, public=False)
        first = report["candidate_summaries"][0]
        self.assertEqual(first["successful_sample_count"], 2)
        self.assertEqual(first["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(first["rejection_counts"]["EGRESS_MISMATCH"], 1)
        self.assertIsNone(report["selection"]["primary_interface"])

    def test_failed_or_wrong_job_samples_do_not_create_recommendation(self):
        samples = [
            sample("Ethernet A"),
            sample("Ethernet A", success=False),
            sample("Ethernet A", job_id="other-job"),
            sample("Ethernet B"),
        ]
        report = build_report(job(), samples, public=False)
        self.assertEqual(report["selection"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(report["selection"]["primary_interface"])

    def test_threshold_failure_is_not_called_ready(self):
        samples = [sample("Ethernet A", down=49) for _ in range(3)]
        report = build_report(job(), samples, public=False)
        first = report["candidate_summaries"][0]
        self.assertEqual(first["status"], "BELOW_CONFIGURED_THRESHOLDS")
        self.assertIn("DOWNLOAD_THRESHOLD_NOT_MET", first["reason_codes"])
        self.assertEqual(report["selection"]["status"], "INSUFFICIENT_EVIDENCE")

    def test_public_report_masks_ip_and_gateway(self):
        samples = [sample("Ethernet A") for _ in range(3)]
        report = build_report(job(), samples, public=True)
        first = report["candidate_summaries"][0]
        self.assertEqual(first["source_ips"], ["192.0.2.x"])
        self.assertEqual(first["gateways"], ["192.0.2.x"])
        serialized = json.dumps(report)
        self.assertNotIn("192.0.2.44", serialized)
        self.assertNotIn("192.0.2.1", serialized)

    def test_ipv6_masking_keeps_only_network_prefix(self):
        self.assertEqual(mask_ip("2001:db8:1234:5678:abcd::1"), "2001:db8:1234:5678::/64")

    def test_job_requires_at_least_three_samples(self):
        payload = job()
        payload["required_samples"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required_samples"):
                load_job(path)

    def test_html_escapes_job_and_interface_names(self):
        payload = job()
        payload["job_id"] = "<script>"
        payload["candidate_interfaces"] = ["Ethernet <A>"]
        report = build_report(payload, [], public=False)
        rendered = render_html(report)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("Ethernet &lt;A&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
