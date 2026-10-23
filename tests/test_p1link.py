"""Tests for the P1Link register map."""

import pytest

from victron_modbus.p1link import P1Link


async def test_meter_and_phase_values(mock_modbus_unit):
    """A full update decodes the totals and every phase's registers."""
    registers = {
        0x2000: 3,  # connected to all three phases
        # Meter totals.
        0x3034: 0,
        0x3035: 12345,  # total_forward_energy: 123.45 kWh
        0x3036: 0,
        0x3037: 6789,  # total_reverse_energy: 67.89 kWh
        0x3080: 0,
        0x3081: 1500,  # power.total: 1500 W
        # Phase L1.
        0x3040: 23010,  # voltage: 230.10 V
        0x3058: 0,
        0x3059: 500,  # current: 5.00 A
        0x3042: 0,
        0x3043: 1000,  # forward_energy: 10.00 kWh
        0x3044: 0,
        0x3045: 200,  # reverse_energy: 2.00 kWh
        0x3082: 0,
        0x3083: 500,  # power.l1: 500 W
        # Phase L2.
        0x3048: 23020,
        0x305A: 0,
        0x305B: 501,
        0x304A: 0,
        0x304B: 1001,
        0x304C: 0,
        0x304D: 201,
        0x3086: 0,
        0x3087: 501,
        # Phase L3.
        0x3050: 23030,
        0x305C: 0,
        0x305D: 502,
        0x3052: 0,
        0x3053: 1002,
        0x3054: 0,
        0x3055: 202,
        0x308A: 0,
        0x308B: 502,
    }
    for address, value in registers.items():
        mock_modbus_unit.holding[address] = value

    device = P1Link(mock_modbus_unit)
    report = await device.async_update()

    assert not report.failed
    assert device.power.total == 1500
    assert device.meter.total_forward_energy == 123.45
    assert device.meter.total_reverse_energy == 67.89

    assert device.phase_1.voltage == 230.10
    assert device.phase_1.current == 5.0
    assert device.power.l1 == 500
    assert device.power.l2 == 501
    assert device.power.l3 == 502
    assert device.phase_1.forward_energy == 10.0
    assert device.phase_1.reverse_energy == 2.0

    assert device.phase_2.voltage == 230.20
    assert device.phase_2.current == 5.01
    assert device.phase_3.voltage == 230.30
    assert device.phase_3.current == 5.02


async def test_maximum_register_values_are_unavailable(mock_modbus_unit):
    """Victron maximum values decode as unavailable rather than measurements."""
    mock_modbus_unit.holding[0x3034] = [0xFFFF, 0xFFFF]
    mock_modbus_unit.holding[0x3040] = 0x7FFF
    mock_modbus_unit.holding[0x3058] = [0x7FFF, 0xFFFF]
    mock_modbus_unit.holding[0x3042] = [0xFFFF, 0xFFFF]
    mock_modbus_unit.holding[0x3044] = [0xFFFF, 0xFFFF]
    mock_modbus_unit.holding[0x3080] = [0x7FFF, 0xFFFF]
    mock_modbus_unit.holding[0x3082] = [0x7FFF, 0xFFFF]

    device = P1Link(mock_modbus_unit)
    await device.async_update()

    assert device.meter.total_forward_energy is None
    assert device.phase_1.voltage is None
    assert device.phase_1.current is None
    assert device.phase_1.forward_energy is None
    assert device.phase_1.reverse_energy is None
    assert device.power.total is None
    assert device.power.l1 is None


async def test_32_bit_current_sentinel_is_unavailable(mock_modbus_unit):
    """The maximum 32-bit current is unavailable."""
    mock_modbus_unit.holding[0x3058] = [0x7FFF, 0xFFFF]

    device = P1Link(mock_modbus_unit)
    await device.async_update()

    assert device.phase_1.current is None


async def test_all_ones_32_bit_current_is_a_reading(mock_modbus_unit):
    """0xFFFFFFFF is -0.01 A for a signed register; only 0x7FFFFFFF is unavailable."""
    mock_modbus_unit.holding[0x3058] = [0xFFFF, 0xFFFF]

    device = P1Link(mock_modbus_unit)
    await device.async_update()

    assert device.phase_1.current == pytest.approx(-0.01)
