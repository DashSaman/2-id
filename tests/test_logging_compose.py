from pathlib import Path
from app.logging import redact


def test_redaction_recursive():
    d=redact({"email":"x","password":"secret","nested":{"api_key":"key","safe":1}})
    assert d["password"]=="[REDACTED]" and d["nested"]["api_key"]=="[REDACTED]" and d["nested"]["safe"]==1


def test_compose_contract():
    text=Path("docker-compose.yml").read_text()
    for expected in ["twoid_postgres","twoid_api","twoid_worker","twoid_bot","twoid_internal","172.28.235.0/24","127.0.0.1:18220:8000","twoid_postgres_data"]:
        assert expected in text
    for forbidden in ["network_mode: host","/var/run/docker.sock","/opt/pv-growth","/opt/akhbot"]:
        assert forbidden not in text
