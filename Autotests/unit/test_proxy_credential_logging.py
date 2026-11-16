from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_telegram_proxy_locations_disable_credential_bearing_logs():
    template = (ROOT / "proxy" / "nginx.conf.template").read_text(encoding="utf-8")
    for location in ("/telegram/", "/telegram-file/"):
        block = template.split(f"location {location} {{", 1)[1].split("}", 1)[0]
        assert "access_log off;" in block
        assert "error_log /dev/null;" in block
