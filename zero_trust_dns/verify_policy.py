#!/usr/bin/env python3
"""Fail-closed validator for the zero-trust DNS policy contract."""

from __future__ import annotations

import copy
import ipaddress
import json
import pathlib
import re
import sys

POLICY_PATH = pathlib.Path(__file__).with_name("policy.json")
TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ENCRYPTED_PREFIXES = ("tls://", "https://", "h3://", "quic://")
QUAD9_BOOTSTRAP = {"9.9.9.9", "149.112.112.112"}


class PolicyError(ValueError):
    pass


def validate(policy: dict) -> None:
    if policy.get("schema_version") != 1:
        raise PolicyError("unsupported schema_version")

    agh = policy["adguard_home"]
    if not re.fullmatch(r"0\.107\.\d+", agh["version"]):
        raise PolicyError("AdGuard Home must be pinned to an explicit stable 0.107.x release")
    for key in ("linux_amd64_sha256", "windows_amd64_sha256"):
        if not SHA256_RE.fullmatch(agh[key]):
            raise PolicyError(f"AdGuard Home {key} must be pinned by SHA-256")

    network = policy["network"]
    if network["public_dns_listener"]:
        raise PolicyError("public DNS listener is forbidden")
    if network["admin_public"]:
        raise PolicyError("public admin UI is forbidden")
    if not network["tailscale_required"]:
        raise PolicyError("authenticated private transport is required")

    allowed = network["allowed_client_cidrs"]
    if not allowed:
        raise PolicyError("allowed_client_cidrs must not be empty")
    for value in allowed:
        net = ipaddress.ip_network(value, strict=True)
        ok = net.is_loopback or (
            net.version == 4 and net.subnet_of(TAILSCALE_V4)
        )
        if not ok:
            raise PolicyError(f"client CIDR is outside loopback/tailnet policy: {value}")

    dns = policy["dns"]
    if not dns["dnssec_do"]:
        raise PolicyError("DNSSEC DO flag must stay enabled")
    if dns["edns_client_subnet"]:
        raise PolicyError("EDNS Client Subnet must stay disabled")
    if not dns["encrypted_upstreams_only"]:
        raise PolicyError("plaintext normal upstream DNS is forbidden")
    upstreams = dns["upstreams"]
    if not upstreams:
        raise PolicyError("at least one encrypted upstream is required")
    for upstream in upstreams:
        if not upstream.startswith(ENCRYPTED_PREFIXES):
            raise PolicyError(f"plaintext/unknown normal upstream rejected: {upstream}")

    bootstrap = set(dns["bootstrap_dns"])
    if not bootstrap or not bootstrap.issubset(QUAD9_BOOTSTRAP):
        raise PolicyError("bootstrap DNS must stay inside the pinned Quad9 bootstrap set")
    if dns["bootstrap_scope"] != "upstream_hostname_resolution_only":
        raise PolicyError("bootstrap DNS scope must remain limited to encrypted-upstream hostname resolution")

    android = policy["android"]
    if android["companion_application_id"] != "io.github.kafka2306.zerotrustdns":
        raise PolicyError("unexpected Android companion application id")
    if android["vpn_provider_application_id"] != "com.tailscale.ipn":
        raise PolicyError("Android dataplane must remain the official Tailscale app")
    if android["canary_domain"] != "ready.zerotrustdns.test":
        raise PolicyError("Android canary domain changed unexpectedly")
    if android["companion_declares_vpn_service"]:
        raise PolicyError("Android companion must not become a VPN provider")
    if android["companion_privileged_permissions"]:
        raise PolicyError("Android companion privileged-permission list must stay empty")

    logging = policy["logging"]
    if not logging["query_log"]:
        raise PolicyError("query logging is required for local audit")
    if logging["commit_query_logs"]:
        raise PolicyError("query logs must never be committed to Git")


def self_test(base: dict) -> None:
    bad_cases = []

    p = copy.deepcopy(base)
    p["network"]["allowed_client_cidrs"] = ["0.0.0.0/0"]
    bad_cases.append(("public client CIDR", p))

    p = copy.deepcopy(base)
    p["dns"]["upstreams"] = ["9.9.9.9"]
    bad_cases.append(("plaintext normal upstream", p))

    p = copy.deepcopy(base)
    p["dns"]["bootstrap_dns"] = ["8.8.8.8"]
    bad_cases.append(("unapproved bootstrap resolver", p))

    p = copy.deepcopy(base)
    p["network"]["admin_public"] = True
    bad_cases.append(("public admin", p))

    p = copy.deepcopy(base)
    p["android"]["companion_declares_vpn_service"] = True
    bad_cases.append(("Android companion VPN privilege creep", p))

    p = copy.deepcopy(base)
    p["android"]["vpn_provider_application_id"] = "io.github.kafka2306.zerotrustdns"
    bad_cases.append(("Android dataplane moved into companion", p))

    p = copy.deepcopy(base)
    p["logging"]["commit_query_logs"] = True
    bad_cases.append(("committed query log", p))

    for name, candidate in bad_cases:
        try:
            validate(candidate)
        except PolicyError:
            print(f"PASS fail-closed: {name}")
        else:
            raise AssertionError(f"unsafe policy was accepted: {name}")


def main() -> int:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    validate(policy)
    print("PASS policy: no public DNS/admin exposure")
    print("PASS policy: clients limited to loopback/Tailscale CGNAT range")
    print("PASS policy: normal upstreams encrypted; bootstrap scope explicit; ECS disabled; DNSSEC DO enabled")
    print("PASS policy: Linux + Windows AdGuard Home artifact SHA-256 pinned")
    print("PASS policy: Android companion cannot become VPN dataplane or request privileged capabilities")
    print("PASS policy: query logs local-only")
    self_test(policy)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL policy: {exc}", file=sys.stderr)
        raise SystemExit(1)
