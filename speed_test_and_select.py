from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Protocol


EXCLUDED_ADAPTER_PATTERN = re.compile(
    r"loopback|vpn|hyper-v|vethernet|wsl|bluetooth|tap|tun|wireguard",
    re.IGNORECASE,
)


class NetworkSafetyError(RuntimeError):
    """Fail-closed error raised when an interface cannot be verified safely."""


@dataclass(frozen=True)
class AdapterState:
    index: int
    name: str
    description: str
    status: str
    admin_status: str
    hardware_interface: bool
    source_ip: str | None
    gateway: str | None
    interface_metric: int | None
    route_metric: int | None

    @property
    def enabled(self) -> bool:
        return self.admin_status.lower() == "up"

    @property
    def connected(self) -> bool:
        return self.status.lower() == "up"

    @property
    def is_virtual(self) -> bool:
        return not self.hardware_interface


@dataclass(frozen=True)
class SpeedSample:
    requested_interface: str
    actual_interface: str | None
    source_ip: str | None
    gateway: str | None
    measurement_server: str | None
    timestamp_utc: str
    duration_seconds: float
    sample_count: int
    latency_ms: float | None
    download_mbps: float | None
    upload_mbps: float | None
    success: bool
    failure_reason: str | None = None
    job_id: str | None = None


class NetworkBackend(Protocol):
    def snapshot(self) -> list[AdapterState]: ...

    def set_enabled(self, index: int, enabled: bool) -> None: ...

    def interface_for_source_ip(self, source_ip: str) -> AdapterState | None: ...


class SpeedTester(Protocol):
    def measure(self, adapter: AdapterState) -> SpeedSample: ...


class PowerShellNetworkBackend:
    """Windows network state adapter using structured PowerShell JSON output."""

    def _run(self, script: str) -> str:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise NetworkSafetyError(
                f"PowerShell command failed with exit code {result.returncode}: {detail}"
            )
        return result.stdout.strip()

    def snapshot(self) -> list[AdapterState]:
        script = r"""
$ErrorActionPreference = 'Stop'
$items = @(Get-NetAdapter -IncludeHidden | ForEach-Object {
    $adapter = $_
    $cfg = Get-NetIPConfiguration -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue
    $ipv4 = @($cfg.IPv4Address | Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1)
    $gateway = @($cfg.IPv4DefaultGateway | Select-Object -First 1)
    $route = @(Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1)
    [pscustomobject]@{
        index = [int]$adapter.ifIndex
        name = [string]$adapter.Name
        description = [string]$adapter.InterfaceDescription
        status = [string]$adapter.Status
        admin_status = [string]$adapter.AdminStatus
        hardware_interface = [bool]$adapter.HardwareInterface
        source_ip = if ($ipv4.Count) { [string]$ipv4[0].IPAddress } else { $null }
        gateway = if ($gateway.Count) { [string]$gateway[0].NextHop } else { $null }
        interface_metric = if ($cfg.NetIPv4Interface) { [int]$cfg.NetIPv4Interface.InterfaceMetric } else { $null }
        route_metric = if ($route.Count) { [int]$route[0].RouteMetric } else { $null }
    }
})
$items | ConvertTo-Json -Depth 4 -Compress
"""
        raw = self._run(script)
        if not raw:
            return []
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = [payload]
        return [AdapterState(**item) for item in payload]

    def set_enabled(self, index: int, enabled: bool) -> None:
        action = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
        expected = "Up" if enabled else "Down"
        script = rf"""
$ErrorActionPreference = 'Stop'
$adapter = Get-NetAdapter -InterfaceIndex {int(index)} -IncludeHidden -ErrorAction Stop
$adapter | {action} -Confirm:$false -ErrorAction Stop
$state = Get-NetAdapter -InterfaceIndex {int(index)} -IncludeHidden -ErrorAction Stop
if ([string]$state.AdminStatus -ne '{expected}') {{
    throw "adapter {int(index)} admin state is $($state.AdminStatus), expected {expected}"
}}
"""
        self._run(script)

    def interface_for_source_ip(self, source_ip: str) -> AdapterState | None:
        for adapter in self.snapshot():
            if adapter.source_ip == source_ip:
                return adapter
        return None


class SpeedtestCliRunner:
    """speedtest-cli adapter. Import is lazy so CI can run without network/dependency."""

    def __init__(self, clock: Callable[[], dt.datetime] | None = None) -> None:
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def measure(self, adapter: AdapterState) -> SpeedSample:
        if not adapter.source_ip:
            raise NetworkSafetyError(f"{adapter.name} has no IPv4 source address")
        try:
            import speedtest  # type: ignore
        except ImportError as exc:
            raise NetworkSafetyError(
                "speedtest-cli is required for live measurement: pip install speedtest-cli"
            ) from exc

        started = time.monotonic()
        measured_at = self._clock().isoformat()
        client = speedtest.Speedtest(source_address=adapter.source_ip, secure=True)
        server = client.get_best_server()
        client.download()
        client.upload()
        result = client.results.dict()
        server_info = result.get("server") or server or {}
        server_label = "/".join(
            str(value)
            for value in (
                server_info.get("id"),
                server_info.get("sponsor"),
                server_info.get("name"),
            )
            if value not in (None, "")
        ) or None
        return SpeedSample(
            requested_interface=adapter.name,
            actual_interface=adapter.name,
            source_ip=adapter.source_ip,
            gateway=adapter.gateway,
            measurement_server=server_label,
            timestamp_utc=measured_at,
            duration_seconds=round(time.monotonic() - started, 3),
            sample_count=1,
            latency_ms=_float_or_none(result.get("ping")),
            download_mbps=round(float(result["download"]) / 1_000_000, 3),
            upload_mbps=round(float(result["upload"]) / 1_000_000, 3),
            success=True,
        )


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)


def eligible_adapters(
    states: Iterable[AdapterState], *, include_virtual: bool = False
) -> list[AdapterState]:
    candidates = []
    for state in states:
        text = f"{state.name} {state.description}"
        if not state.enabled or not state.connected or not state.source_ip:
            continue
        if not include_virtual and (state.is_virtual or EXCLUDED_ADAPTER_PATTERN.search(text)):
            continue
        candidates.append(state)
    return sorted(candidates, key=lambda item: (item.interface_metric or 999999, item.index))


def restore_adapter_states(
    backend: NetworkBackend, original: Iterable[AdapterState]
) -> None:
    errors: list[str] = []
    current = {item.index: item for item in backend.snapshot()}
    for before in original:
        after = current.get(before.index)
        if after is None:
            errors.append(f"adapter {before.index} ({before.name}) disappeared")
            continue
        if after.enabled != before.enabled:
            try:
                backend.set_enabled(before.index, before.enabled)
            except Exception as exc:
                errors.append(f"{before.name}: {exc}")
    if errors:
        raise NetworkSafetyError("restore failed: " + "; ".join(errors))


def isolate_adapter(
    backend: NetworkBackend,
    target: AdapterState,
    candidates: Iterable[AdapterState],
) -> None:
    for candidate in candidates:
        backend.set_enabled(candidate.index, candidate.index == target.index)

    actual = backend.interface_for_source_ip(target.source_ip or "")
    if actual is None or actual.index != target.index:
        actual_name = actual.name if actual else "unresolved"
        raise NetworkSafetyError(
            f"requested interface {target.name} does not own source IP {target.source_ip}; "
            f"resolved={actual_name}"
        )


def run_measurements(
    backend: NetworkBackend,
    tester: SpeedTester,
    *,
    dry_run: bool = False,
    include_virtual: bool = False,
    isolate: bool = True,
    settle_seconds: float = 0.0,
    on_sample: Callable[[SpeedSample], None] | None = None,
    job_id: str | None = None,
) -> list[SpeedSample]:
    original = backend.snapshot()
    candidates = eligible_adapters(original, include_virtual=include_virtual)
    if not candidates:
        raise NetworkSafetyError("no eligible connected physical adapter with an IPv4 address")
    if dry_run:
        return []

    results: list[SpeedSample] = []
    try:
        for candidate in candidates:
            actual: AdapterState | None = None
            try:
                if isolate:
                    isolate_adapter(backend, candidate, candidates)
                    if settle_seconds:
                        time.sleep(settle_seconds)
                actual = backend.interface_for_source_ip(candidate.source_ip or "")
                if actual is None or actual.index != candidate.index:
                    actual_name = actual.name if actual else "unresolved"
                    raise NetworkSafetyError(
                        f"egress ownership mismatch: requested={candidate.name}, actual={actual_name}"
                    )
                sample = tester.measure(candidate)
                if sample.actual_interface != actual.name:
                    raise NetworkSafetyError(
                        f"tester reported egress mismatch: requested={candidate.name}, "
                        f"actual={sample.actual_interface}"
                    )
                sample = replace(sample, job_id=job_id)
                results.append(sample)
                if on_sample:
                    on_sample(sample)
            except BaseException as exc:
                failure = SpeedSample(
                    requested_interface=candidate.name,
                    actual_interface=(actual.name if actual else None),
                    source_ip=candidate.source_ip,
                    gateway=candidate.gateway,
                    measurement_server=None,
                    timestamp_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    duration_seconds=0.0,
                    sample_count=0,
                    latency_ms=None,
                    download_mbps=None,
                    upload_mbps=None,
                    success=False,
                    failure_reason=f"{type(exc).__name__}: {exc}",
                    job_id=job_id,
                )
                if on_sample:
                    on_sample(failure)
                raise
            finally:
                restore_adapter_states(backend, original)
    finally:
        restore_adapter_states(backend, original)
    return results


def default_log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "BestEthernet" / "logs" if base else Path.home() / ".bestethernet" / "logs"


def write_results(results: Iterable[SpeedSample], log_dir: Path) -> None:
    rows = list(results)
    log_dir.mkdir(parents=True, exist_ok=True)
    jsonl = log_dir / "measurements.jsonl"
    csv_path = log_dir / "measurements.csv"
    with jsonl.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False, sort_keys=True) + "\n")
    new_csv = not csv_path.exists()
    fieldnames = list(SpeedSample.__dataclass_fields__)
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if new_csv:
            writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely benchmark Windows network adapters")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show eligible adapters without changing network state or files",
    )
    parser.add_argument(
        "--include-virtual", action="store_true", help="Include virtual/VPN-like adapters"
    )
    parser.add_argument(
        "--no-isolate",
        action="store_true",
        help="Bind the source IP but do not disable other candidates",
    )
    parser.add_argument(
        "--settle-seconds", type=float, default=2.0, help="Seconds to wait after isolation"
    )
    parser.add_argument(
        "--log-dir", type=Path, default=default_log_dir(), help="Directory for JSONL/CSV audit logs"
    )
    parser.add_argument(
        "--job-id",
        help="Optional stable readiness job ID written to every audit sample",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend = PowerShellNetworkBackend()
    original = backend.snapshot()
    candidates = eligible_adapters(original, include_virtual=args.include_virtual)
    print("Eligible adapters:")
    for adapter in candidates:
        print(
            f"- {adapter.name} (ifIndex={adapter.index}, source={adapter.source_ip}, "
            f"gateway={adapter.gateway})"
        )
    if args.dry_run:
        candidate_indexes = {item.index for item in candidates}
        print("Excluded adapters:")
        for adapter in original:
            if adapter.index not in candidate_indexes:
                print(
                    f"- {adapter.name} (ifIndex={adapter.index}, admin={adapter.admin_status}, "
                    f"link={adapter.status}, hardware={adapter.hardware_interface})"
                )
        print(
            "Plan: isolate one eligible adapter at a time, bind speedtest to its source IPv4, "
            "then restore every adapter to its original administrative state."
        )
        print("Routes are observed for audit only; this command does not modify routes.")
        print("Dry-run: no adapter state, route or file was changed.")
        return 0

    results = run_measurements(
        backend,
        SpeedtestCliRunner(),
        include_virtual=args.include_virtual,
        isolate=not args.no_isolate,
        settle_seconds=args.settle_seconds,
        on_sample=lambda sample: write_results([sample], args.log_dir),
        job_id=args.job_id,
    )
    for result in results:
        print(
            f"{result.requested_interface}: {result.download_mbps} Mbps down / "
            f"{result.upload_mbps} Mbps up / {result.latency_ms} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
