import dataclasses
import tempfile
import unittest
from pathlib import Path

from speed_test_and_select import (
    AdapterState,
    NetworkSafetyError,
    SpeedSample,
    eligible_adapters,
    run_measurements,
    write_results,
)


def adapter(index, name, *, enabled=True, connected=True, hardware=True, ip=None):
    return AdapterState(
        index=index,
        name=name,
        description=name,
        status="Up" if connected else "Disconnected",
        admin_status="Up" if enabled else "Down",
        hardware_interface=hardware,
        source_ip=ip or f"192.0.2.{index}",
        gateway="192.0.2.1",
        interface_metric=index,
        route_metric=10,
    )


class FakeBackend:
    def __init__(self, states, *, fail_on_set=None, source_owner=None):
        self.states = {item.index: item for item in states}
        self.fail_on_set = fail_on_set
        self.source_owner = source_owner or {item.source_ip: item.index for item in states}
        self.set_calls = []

    def snapshot(self):
        return list(self.states.values())

    def set_enabled(self, index, enabled):
        self.set_calls.append((index, enabled))
        if self.fail_on_set == (index, enabled):
            raise NetworkSafetyError("injected switch failure")
        current = self.states[index]
        self.states[index] = dataclasses.replace(
            current,
            admin_status="Up" if enabled else "Down",
            status="Up" if enabled else "Disabled",
        )

    def interface_for_source_ip(self, source_ip):
        index = self.source_owner.get(source_ip)
        return self.states.get(index) if index is not None else None


class FakeTester:
    def __init__(self, *, failure=None, actual_name=None):
        self.failure = failure
        self.actual_name = actual_name
        self.calls = []

    def measure(self, item):
        self.calls.append(item.name)
        if self.failure:
            raise self.failure
        return SpeedSample(
            requested_interface=item.name,
            actual_interface=self.actual_name or item.name,
            source_ip=item.source_ip,
            gateway=item.gateway,
            measurement_server="fixture/server",
            timestamp_utc="2026-08-08T00:00:00+00:00",
            duration_seconds=1.0,
            sample_count=1,
            latency_ms=10.0,
            download_mbps=100.0,
            upload_mbps=50.0,
            success=True,
        )


class NetworkSafetyTests(unittest.TestCase):
    def setUp(self):
        self.a = adapter(1, "Ethernet A")
        self.b = adapter(2, "Ethernet B")

    def assert_original_state(self, backend):
        self.assertTrue(backend.states[1].enabled)
        self.assertTrue(backend.states[2].enabled)

    def test_two_active_adapters_are_measured_with_requested_binding(self):
        backend = FakeBackend([self.a, self.b])
        tester = FakeTester()
        results = run_measurements(backend, tester, settle_seconds=0)
        self.assertEqual([r.requested_interface for r in results], ["Ethernet A", "Ethernet B"])
        self.assertEqual(tester.calls, ["Ethernet A", "Ethernet B"])
        self.assert_original_state(backend)

    def test_egress_owner_mismatch_is_rejected_before_measurement(self):
        backend = FakeBackend(
            [self.a, self.b], source_owner={self.a.source_ip: 2, self.b.source_ip: 2}
        )
        tester = FakeTester()
        with self.assertRaisesRegex(NetworkSafetyError, "does not own source IP"):
            run_measurements(backend, tester, settle_seconds=0)
        self.assertEqual(tester.calls, [])
        self.assert_original_state(backend)

    def test_switch_failure_prevents_measurement_and_rolls_back(self):
        backend = FakeBackend([self.a, self.b], fail_on_set=(2, False))
        tester = FakeTester()
        with self.assertRaisesRegex(NetworkSafetyError, "switch failure"):
            run_measurements(backend, tester, settle_seconds=0)
        self.assertEqual(tester.calls, [])
        self.assert_original_state(backend)

    def test_measurement_exception_restores_original_state(self):
        backend = FakeBackend([self.a, self.b])
        tester = FakeTester(failure=RuntimeError("speed test failed"))
        with self.assertRaisesRegex(RuntimeError, "speed test failed"):
            run_measurements(backend, tester, settle_seconds=0)
        self.assert_original_state(backend)

    def test_measurement_failure_emits_auditable_failure_record(self):
        backend = FakeBackend([self.a, self.b])
        tester = FakeTester(failure=RuntimeError("speed test failed"))
        audit = []
        with self.assertRaisesRegex(RuntimeError, "speed test failed"):
            run_measurements(backend, tester, settle_seconds=0, on_sample=audit.append)
        self.assertEqual(len(audit), 1)
        self.assertFalse(audit[0].success)
        self.assertIn("speed test failed", audit[0].failure_reason)
        self.assertEqual(audit[0].requested_interface, "Ethernet A")

    def test_keyboard_interrupt_restores_original_state(self):
        backend = FakeBackend([self.a, self.b])
        tester = FakeTester(failure=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            run_measurements(backend, tester, settle_seconds=0)
        self.assert_original_state(backend)

    def test_log_write_failure_restores_original_state(self):
        backend = FakeBackend([self.a, self.b])

        def fail_log(_sample):
            raise OSError("disk full")

        with self.assertRaisesRegex(OSError, "disk full"):
            run_measurements(backend, FakeTester(), settle_seconds=0, on_sample=fail_log)
        self.assert_original_state(backend)

    def test_initially_disabled_adapter_stays_disabled(self):
        disabled = adapter(3, "Ethernet C", enabled=False, connected=False)
        backend = FakeBackend([self.a, self.b, disabled])
        run_measurements(backend, FakeTester(), settle_seconds=0)
        self.assertFalse(backend.states[3].enabled)

    def test_virtual_and_vpn_adapters_are_excluded_by_default(self):
        virtual = adapter(3, "vEthernet (WSL)", hardware=False)
        vpn = adapter(4, "Corporate VPN", hardware=True)
        self.assertEqual(eligible_adapters([self.a, virtual, vpn]), [self.a])

    def test_dry_run_changes_nothing_and_does_not_measure(self):
        backend = FakeBackend([self.a, self.b])
        tester = FakeTester()
        self.assertEqual(run_measurements(backend, tester, dry_run=True), [])
        self.assertEqual(backend.set_calls, [])
        self.assertEqual(tester.calls, [])
        self.assert_original_state(backend)

    def test_tester_reported_interface_mismatch_is_rejected(self):
        backend = FakeBackend([self.a, self.b])
        tester = FakeTester(actual_name="Wrong interface")
        with self.assertRaisesRegex(NetworkSafetyError, "tester reported egress mismatch"):
            run_measurements(backend, tester, settle_seconds=0)
        self.assert_original_state(backend)

    def test_logs_are_auditable_and_portable(self):
        sample = FakeTester().measure(self.a)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            write_results([sample], path)
            text = (path / "measurements.jsonl").read_text(encoding="utf-8")
            self.assertIn('"requested_interface": "Ethernet A"', text)
            self.assertIn('"source_ip": "192.0.2.1"', text)
            self.assertTrue((path / "measurements.csv").exists())


if __name__ == "__main__":
    unittest.main()
