"""Limity pamięci i logowanie wszystkich usług w docker-compose.yml (k8): Grafana 512m + GOMEMLIMIT, sterownik logów `local` z rotacją."""
from __future__ import annotations

import yaml

from dbtools import REPO


def services():
    with open(REPO / "docker-compose.yml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["services"]


def test_every_service_has_a_memory_limit_equal_to_the_swap_limit():
    for name, svc in services().items():
        assert svc.get("mem_limit"), name
        if "memswap_limit" in svc:
            assert svc["memswap_limit"] == svc["mem_limit"], name


def test_grafana_limit_and_go_memory_limit():
    svc = services()["grafana"]
    assert svc["mem_limit"] == "512m" and svc["memswap_limit"] == "512m"
    assert svc["environment"]["GOMEMLIMIT"] == "400MiB"            # poniżej mem_limit: GC reaguje przed OOM-killerem


def test_all_services_log_with_the_local_driver_and_rotation():
    for name, svc in services().items():
        logging = svc["logging"]
        assert logging["driver"] == "local", name
        assert logging["options"] == {"max-size": "10m", "max-file": "5"}, name


def test_memory_limits_sum_fits_the_budget():
    def mib(text):
        return int(text[:-1]) * (1024 if text.endswith("g") else 1)
    # usługi z profilem (np. simulator-tools, E3-k5) uruchamia się jednorazowo, nie działają stale
    total = sum(mib(svc["mem_limit"]) for svc in services().values() if not svc.get("profiles"))
    assert total <= 2560, total                    # 16 GB komputera, smartWARE ok. 0,4-1 GB: limity razem poniżej 2,5 GiB
