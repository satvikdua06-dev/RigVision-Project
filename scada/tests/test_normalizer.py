"""Unit tests for scada/normalizer.py."""
import math
import pytest
from scada.drivers.base import RawReading
from scada.normalizer import normalize


def _raw(sensor_id="temp_a", raw_value=285.0, protocol="modbus",
         scale=0.1, offset=0.0, unit="degC"):
    return RawReading(
        sensor_id=sensor_id,
        raw_value=raw_value,
        protocol=protocol,
        device="test",
        config={"scale": scale, "offset": offset, "unit": unit},
    )


def test_correct_scaling():
    nr = normalize(_raw(sensor_id="temp_a", raw_value=285.0, scale=0.1, offset=0.0, unit="degC"))
    assert nr is not None
    assert abs(nr.value - 28.5) < 0.001
    assert nr.unit == "degC"
    assert nr.quality == "good"


def test_unknown_sensor_returns_none():
    nr = normalize(_raw(sensor_id="nonexistent_xyz_sensor"))
    assert nr is None


def test_nan_quality_bad():
    nr = normalize(_raw(sensor_id="temp_a", raw_value=float("nan")))
    assert nr is not None
    assert nr.quality == "bad"


def test_scale_with_offset():
    nr = normalize(_raw(sensor_id="temp_a", raw_value=100.0, scale=0.5, offset=-10.0))
    assert nr is not None
    assert abs(nr.value - 40.0) < 0.001


def test_mqtt_protocol_field():
    nr = normalize(_raw(sensor_id="temp_b", protocol="mqtt",
                        raw_value=30.0, scale=1.0, offset=0.0, unit="degC"))
    assert nr is not None
    assert nr.protocol == "mqtt"
