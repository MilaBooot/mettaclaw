import pytest

from monitor.config import ConfigurationError, MonitorConfig


def test_credentials_are_required():
    with pytest.raises(ConfigurationError, match="required"):
        MonitorConfig.from_env({})


def test_short_password_is_rejected():
    with pytest.raises(ConfigurationError, match="at least 12"):
        MonitorConfig.from_env(
            {"OMA_MONITOR_USERNAME": "operator", "OMA_MONITOR_PASSWORD": "short"}
        )


def test_container_defaults_to_omega():
    config = MonitorConfig.from_env(
        {
            "OMA_MONITOR_USERNAME": "operator",
            "OMA_MONITOR_PASSWORD": "a-long-test-password",
        }
    )
    assert config.container_name == "omega"
    assert config.host == "127.0.0.1"


@pytest.mark.parametrize("name", ["", "other/container", "--privileged", "has space"])
def test_invalid_container_name_is_rejected(name):
    with pytest.raises(ConfigurationError, match="container name"):
        MonitorConfig.from_env(
            {
                "OMA_MONITOR_USERNAME": "operator",
                "OMA_MONITOR_PASSWORD": "a-long-test-password",
                "OMA_MONITOR_CONTAINER": name,
            }
        )

