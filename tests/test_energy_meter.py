"""Tests for the identification and polling every energy meter model shares."""

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.cli_helper import CountingUnit
from modbus_connection.encode import encode_string

from victron_modbus import (
    FAST_SUB_SYSTEMS,
    SLOW_SUB_SYSTEMS,
    UnsupportedDeviceError,
    async_identify,
    sentinels,
)
from victron_modbus._energy_meter import (
    ATTEMPTS,
    REQUEST_TIMEOUT,
    PhaseBlock,
    Power,
)
from victron_modbus.vm_3p5a import VM3P5A
from victron_modbus.vm_3p75ct import VM3P75CT

# Every model shares its polling and identification logic (``EnergyMeter``), so
# tests of that logic run on one model. Tests of what differs per model, the
# register maps, run on each of them.
DEVICES = pytest.mark.parametrize("device_class", [VM3P75CT, VM3P5A])


@pytest.fixture
def device_class() -> type[VM3P75CT]:
    """The model the shared-logic tests run on."""
    return VM3P75CT


def _set_info(unit, product_id: int, serial: str = "HQ2345ABCDE") -> None:
    unit.holding[0x1000] = product_id
    unit.holding[0x1001] = encode_string(serial, length=8)
    unit.holding[0x100B] = 3


@pytest.mark.parametrize(
    ("product_id", "device_class"),
    [(0xA1B1, VM3P75CT), (0xA1B5, VM3P75CT), (0xA1B2, VM3P5A)],
)
async def test_identify(mock_modbus_unit, product_id, device_class):
    """The product ID selects the device class."""
    _set_info(mock_modbus_unit, product_id)

    device = await async_identify(mock_modbus_unit)

    assert type(device) is device_class


async def test_identify_unsupported_product(mock_modbus_unit):
    """An unknown product ID is reported, not guessed."""
    _set_info(mock_modbus_unit, 0xA389)

    with pytest.raises(UnsupportedDeviceError, match="0xA389") as err:
        await async_identify(mock_modbus_unit)
    assert err.value.product_id == 0xA389


async def test_identify_keeps_the_identification(mock_modbus_unit):
    """The identification read while identifying is not read again."""
    _set_info(mock_modbus_unit, 0xA1B1)

    device = await async_identify(mock_modbus_unit)
    assert device.info.serial_number == "HQ2345ABCDE"

    mock_modbus_unit.fail_read(0x1000, IllegalDataAddressError())
    await device.async_ensure_setup()
    report = await device.async_update()
    assert report.complete


async def test_identify_sets_a_short_timeout(mock_modbus_unit):
    """A lost UDP datagram must not stall setup for the default timeout."""
    _set_info(mock_modbus_unit, 0xA1B1)

    await async_identify(mock_modbus_unit)

    assert mock_modbus_unit.required_timeout == REQUEST_TIMEOUT


def test_device_sets_a_short_timeout(mock_modbus_unit, device_class):
    """A lost UDP datagram must not stall a poll for the default timeout."""
    device_class(mock_modbus_unit)

    assert mock_modbus_unit.required_timeout == REQUEST_TIMEOUT


async def test_info_is_read_once(mock_modbus_unit, device_class):
    """The identification is read on the first poll, not on every poll."""
    _set_info(mock_modbus_unit, 0xA1B1)
    device = device_class(mock_modbus_unit)

    await device.async_update()
    assert device.info.serial_number == "HQ2345ABCDE"
    assert device.info.hardware_version == 3

    mock_modbus_unit.fail_read(0x1000, IllegalDataAddressError())
    report = await device.async_update()
    assert report.complete


async def test_raw_registers_are_merged(mock_modbus_unit, device_class):
    """Diagnostics contain the raw registers read by the device."""
    _set_info(mock_modbus_unit, 0xA1B1)
    mock_modbus_unit.holding[0x3080] = [0, 1500]
    mock_modbus_unit.holding[0x3040] = 23010

    raw = await device_class(mock_modbus_unit).async_read_raw()

    assert raw["holding"][0x1000] == 0xA1B1
    assert raw["holding"][0x3081] == 1500
    assert raw["holding"][0x3040] == 23010


async def test_timeout_before_any_response_is_raised(mock_modbus_unit, device_class):
    """A device that answers no requests raises the first timeout."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())

    with pytest.raises(ModbusTimeoutError):
        await device_class(mock_modbus_unit).async_update()


async def test_connection_error_is_raised(mock_modbus_unit, device_class):
    """A dropped connection is propagated immediately."""
    mock_modbus_unit.fail_requests(ModbusConnectionError())

    with pytest.raises(ModbusConnectionError):
        await device_class(mock_modbus_unit).async_update()


@pytest.mark.parametrize("error", [ModbusTimeoutError, IllegalDataAddressError])
async def test_phase_failure_is_reported(mock_modbus_unit, device_class, error):
    """A failure after the meter answered keeps the meter update."""
    mock_modbus_unit.fail_read(0x3040, error())
    listener_calls: list[str] = []

    device = device_class(mock_modbus_unit)
    device.meter.add_update_listener(lambda: listener_calls.append("meter"))
    device.phase_1.add_update_listener(lambda: listener_calls.append("phase_1"))
    report = await device.async_update()

    assert report.updated == {"power", "meter"}
    assert isinstance(report.failed["phases"], error)
    assert listener_calls == ["meter"]


async def test_lost_datagram_is_retried(mock_modbus_unit, device_class):
    """A sub-system that fails once while another answered is read again."""
    mock_modbus_unit.holding[0x3040] = 23010
    failures = [ModbusTimeoutError()]
    read = mock_modbus_unit.read_holding_registers

    async def read_losing_one(address: int, count: int) -> list[int]:
        if address <= 0x3040 < address + count and failures:
            raise failures.pop()
        return await read(address, count)

    mock_modbus_unit.read_holding_registers = read_losing_one
    device = device_class(mock_modbus_unit)
    report = await device.async_update()

    assert report.complete
    assert report.updated == {"power", "meter", "phases"}
    assert device.phase_1.voltage == 230.10


async def test_persistent_failure_is_reported_after_retry(
    mock_modbus_unit, device_class
):
    """A sub-system that fails again on the retry is reported as failed."""
    mock_modbus_unit.fail_read(0x3040, ModbusTimeoutError())

    report = await device_class(mock_modbus_unit).async_update()

    assert report.updated == {"power", "meter"}
    assert isinstance(report.failed["phases"], ModbusTimeoutError)


async def test_nothing_answering_is_not_retried(mock_modbus_unit, device_class):
    """When no sub-system answered, the poll is not repeated."""
    for address in (0x3080, 0x3034, 0x3040):
        mock_modbus_unit.fail_read(address, IllegalDataAddressError())
    counting = CountingUnit(mock_modbus_unit)
    device = device_class(counting)
    await device.async_ensure_setup()
    reads = counting.reads

    report = await device.async_update()

    assert not report.updated
    assert set(report.failed) == {"power", "meter", "phases"}
    assert counting.reads - reads == 3  # one failed read each, no retries


def _lose_reads(unit, address: int, times: int) -> list[int]:
    """Lose the next ``times`` reads that include ``address``; log every read."""
    reads: list[int] = []
    lost = [ModbusTimeoutError()] * times
    read = unit.read_holding_registers

    async def read_losing(start: int, count: int) -> list[int]:
        if start <= address < start + count:
            reads.append(address)
            if lost:
                raise lost.pop()
        return await read(start, count)

    unit.read_holding_registers = read_losing
    return reads


async def test_lost_datagrams_before_any_answer_are_retried(
    mock_modbus_unit, device_class
):
    """Over a lossy link even the first read of a poll is tried again."""
    mock_modbus_unit.holding[0x3081] = 1500
    reads = _lose_reads(mock_modbus_unit, 0x3080, ATTEMPTS - 1)
    device = device_class(mock_modbus_unit)
    await device.async_ensure_setup()

    report = await device.async_update(FAST_SUB_SYSTEMS)

    assert report.complete
    assert device.power.total == 1500
    assert len(reads) == ATTEMPTS


async def test_attempts_are_limited(mock_modbus_unit, device_class):
    """A read that keeps timing out is tried ATTEMPTS times, then raised."""
    reads = _lose_reads(mock_modbus_unit, 0x3080, 100)
    device = device_class(mock_modbus_unit)
    await device.async_ensure_setup()

    with pytest.raises(ModbusTimeoutError):
        await device.async_update(FAST_SUB_SYSTEMS)

    assert len(reads) == ATTEMPTS


async def test_lost_datagrams_are_retried_after_a_partial_poll(
    mock_modbus_unit, device_class
):
    """A sub-system that times out repeatedly after others answered recovers."""
    mock_modbus_unit.holding[0x3040] = 23010
    reads = _lose_reads(mock_modbus_unit, 0x3040, ATTEMPTS - 1)
    device = device_class(mock_modbus_unit)

    report = await device.async_update()

    assert report.complete
    assert device.phase_1.voltage == 230.10
    assert len(reads) == ATTEMPTS


async def test_lost_datagram_does_not_hide_a_refusal(mock_modbus_unit, device_class):
    """Retrying what timed out leaves a sub-system the device refused as failed."""
    mock_modbus_unit.fail_read(0x3034, IllegalDataAddressError())
    reads = _lose_reads(mock_modbus_unit, 0x3040, 1)
    device = device_class(mock_modbus_unit)

    report = await device.async_update()

    assert report.updated == {"power", "phases"}
    assert isinstance(report.failed["meter"], IllegalDataAddressError)
    assert len(reads) == 2


async def test_identify_retries_a_lost_datagram(mock_modbus_unit):
    """The product ID is read again when the first request is lost."""
    mock_modbus_unit.holding[0x1000] = 0xA1B5
    reads = _lose_reads(mock_modbus_unit, 0x1000, ATTEMPTS - 1)

    device = await async_identify(mock_modbus_unit)

    assert isinstance(device, VM3P75CT)
    assert len(reads) == ATTEMPTS


async def test_setup_retries_lost_datagrams(mock_modbus_unit, device_class):
    """A lost datagram in setup doesn't change what the meter is taken to have."""
    mock_modbus_unit.holding[0x2000] = 0  # connected to L1 only
    config_reads = _lose_reads(mock_modbus_unit, 0x2000, 1)
    device = device_class(mock_modbus_unit)

    await device.async_ensure_setup()

    assert device.connected_phases == (1,)
    assert len(config_reads) == 2


async def test_setup_retries_a_lost_fine_frequency_probe(mock_modbus_unit):
    """A lost datagram doesn't make the meter look like it lacks fine frequency."""
    mock_modbus_unit.holding[0x303E] = 50012
    reads = _lose_reads(mock_modbus_unit, 0x303E, 1)
    device = VM3P75CT(mock_modbus_unit)

    await device.async_update(SLOW_SUB_SYSTEMS)

    assert device.meter.frequency_fine == 50.012
    assert len(reads) == 3  # the lost probe, the probe, then the poll


@DEVICES
async def test_minus_one_watt_is_a_reading(mock_modbus_unit, device_class):
    """0xFFFFFFFF is -1 W for a signed register; only 0x7FFFFFFF is unavailable."""
    mock_modbus_unit.holding[0x2000] = 3
    mock_modbus_unit.holding[0x3080] = [0xFFFF, 0xFFFF]
    mock_modbus_unit.holding[0x3082] = [0xFFFF, 0xFFFF]
    mock_modbus_unit.holding[0x3086] = [0x7FFF, 0xFFFF]

    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.power.total == -1
    assert device.power.l1 == -1
    assert device.power.l2 is None


async def test_negative_power_is_a_valid_reading(mock_modbus_unit, device_class):
    """Any other negative power is a real reading: power exported to the grid."""
    mock_modbus_unit.holding[0x3080] = [0xFFFF, 0xFFFE]  # -2 W

    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.power.total == -2


async def test_unreported_hardware_version(mock_modbus_unit):
    """A device that reports no hardware version gets None, not 65535."""
    _set_info(mock_modbus_unit, 0xA1B1)
    mock_modbus_unit.holding[0x100B] = 0xFFFF

    device = await async_identify(mock_modbus_unit)

    assert device.info.hardware_version is None


@pytest.mark.parametrize(
    ("names", "polled"),
    [
        (FAST_SUB_SYSTEMS, {"power"}),
        (SLOW_SUB_SYSTEMS, {"meter", "phases"}),
    ],
)
async def test_poll_fast_and_slow_apart(mock_modbus_unit, device_class, names, polled):
    """Power can be polled on its own, and the rest without it."""
    report = await device_class(mock_modbus_unit).async_update(names)

    assert report.updated == polled


@DEVICES
async def test_reads_only_declared_registers(mock_modbus_unit, device_class):
    """A read stays within the declared fields and readable ranges."""
    device = device_class(mock_modbus_unit)
    read: set[int] = set()
    original = mock_modbus_unit.read_holding_registers

    async def recording_read(address: int, count: int) -> list[int]:
        read.update(range(address, address + count))
        return await original(address, count)

    mock_modbus_unit.read_holding_registers = recording_read
    await device.async_update()

    components = (device.info, device.config, device.power, device.meter)
    declared = {
        address
        for component in (*components, *_phases(device))
        if component is not None
        for address in _addresses(component)
    }
    assert read <= declared


@DEVICES
@pytest.mark.parametrize("sub_system", ["power", "phases"])
async def test_one_request_per_poll(mock_modbus_unit, device_class, sub_system):
    """Power and the three phases are each read in a single request."""
    device = device_class(mock_modbus_unit)
    await device.async_update(["power"])  # set up first
    original = mock_modbus_unit.read_holding_registers
    requests: list[tuple[int, int]] = []

    async def recording_read(address: int, count: int) -> list[int]:
        requests.append((address, count))
        return await original(address, count)

    mock_modbus_unit.read_holding_registers = recording_read
    report = await device.async_update([sub_system])

    assert report.updated == {sub_system}
    assert len(requests) == 1


def _phases(device):
    return (device.phase_1, device.phase_2, device.phase_3)


def _addresses(component) -> set[int]:
    fields = {
        address
        for resolved in component.resolved_fields.values()
        for address in range(resolved.address, resolved.address + resolved.count)
    }
    ranges = {
        address
        for low, high in component.register_ranges or ()
        for address in range(low, high + 1)
    }
    return fields | ranges


VM_METERS = pytest.mark.parametrize("device_class", [VM3P75CT, VM3P5A])


@VM_METERS
async def test_fine_frequency(mock_modbus_unit, device_class):
    """The meters read the grid frequency in 0.001 Hz as well as in 0.01 Hz."""
    mock_modbus_unit.holding[0x3032] = 5001
    mock_modbus_unit.holding[0x303E] = 50012

    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.meter.frequency == 50.01
    assert device.meter.frequency_fine == 50.012


@VM_METERS
async def test_fine_frequency_missing_from_firmware(mock_modbus_unit, device_class):
    """Firmware without 0x303E: it is tried once, then never read again."""
    mock_modbus_unit.holding[0x3032] = 5001
    mock_modbus_unit.fail_read(0x303E, IllegalDataAddressError())
    read: list[int] = []
    original = mock_modbus_unit.read_holding_registers

    async def recording_read(address: int, count: int) -> list[int]:
        read.extend(range(address, address + count))
        return await original(address, count)

    mock_modbus_unit.read_holding_registers = recording_read
    device = device_class(mock_modbus_unit)
    report = await device.async_update()
    await device.async_update()

    assert report.complete
    assert device.meter.frequency == 50.01
    assert device.meter.frequency_fine is None
    assert read.count(0x303E) == 1  # only the setup-time probe


@VM_METERS
async def test_fine_frequency_unavailable(mock_modbus_unit, device_class):
    """A meter that has the register but no fine value reports 0xFFFF."""
    mock_modbus_unit.holding[0x303E] = 0xFFFF

    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.meter.frequency_fine is None


@pytest.mark.parametrize(
    ("config", "connected"),
    [
        (0, (1,)),
        (1, (2,)),
        (2, (3,)),
        (3, (1, 2, 3)),
        (4, (1, 2)),
        (9, (1, 2, 3)),  # unknown: assume three phases, as Victron's driver does
    ],
)
async def test_connected_phases(mock_modbus_unit, device_class, config, connected):
    """The phase configuration register says which phases are connected."""
    mock_modbus_unit.holding[0x2000] = config

    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.connected_phases == connected


async def test_phase_config_missing(mock_modbus_unit, device_class):
    """A meter without the phase configuration register is taken as three-phase."""
    mock_modbus_unit.fail_read(0x2000, IllegalDataAddressError())

    device = device_class(mock_modbus_unit)
    report = await device.async_update()

    assert report.complete
    assert device.config is None
    assert device.connected_phases == (1, 2, 3)


@DEVICES
@pytest.mark.parametrize(
    ("config", "connected"),
    [(0, (1,)), (1, (2,)), (2, (3,)), (3, (1, 2, 3)), (4, (1, 2))],
)
async def test_unconnected_phases_read_as_unavailable(
    mock_modbus_unit, device_class, config, connected
):
    """A meter reports an unused phase with all bits set; it stays unavailable."""
    mock_modbus_unit.holding[0x2000] = config
    mock_modbus_unit.holding[0x3080] = [0, 300]
    for number in (1, 2, 3):
        used = number in connected
        mock_modbus_unit.holding[0x3040 + 8 * (number - 1)] = (
            23000 + number if used else 0xFFFF
        )
        mock_modbus_unit.holding[(0x3082, 0x3086, 0x308A)[number - 1]] = (
            [0, 100 * number] if used else [0xFFFF, 0xFFFF]
        )

    device = device_class(mock_modbus_unit)
    report = await device.async_update()

    assert report.complete
    assert device.power.total == 300
    for number, phase in enumerate(_phases(device), 1):
        power = (device.power.l1, device.power.l2, device.power.l3)[number - 1]
        if number in connected:
            assert phase.voltage == (23000 + number) / 100
            assert power == 100 * number
        else:
            assert phase.voltage is None
            assert power is None


@DEVICES
async def test_unconnected_phases_are_not_polled(mock_modbus_unit, device_class):
    """With one phase connected, the other phases' fields are left out of the read."""
    mock_modbus_unit.holding[0x2000] = 0
    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.phases is not None
    assert set(device.power.resolved_fields) == {"total", "l1"}


async def test_all_ones_signed_voltage_is_a_reading(mock_modbus_unit, device_class):
    """0xFFFF is -0.01 V for a signed register; only 0x7FFF is unavailable."""
    mock_modbus_unit.holding[0x3040] = 0xFFFF

    device = device_class(mock_modbus_unit)
    await device.async_update()

    assert device.phase_1.voltage == pytest.approx(-0.01)


class _ReadCounter:
    """Counts every read made through a mock unit."""

    def __init__(self, unit) -> None:
        self.count = 0
        original = unit.read_holding_registers

        async def counting_read(address: int, count: int) -> list[int]:
            self.count += 1
            return await original(address, count)

        unit.read_holding_registers = counting_read


async def test_dead_device_costs_attempts_timeouts(mock_modbus_unit, device_class):
    """A fresh device that answers nothing makes exactly ATTEMPTS reads."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    counter = _ReadCounter(mock_modbus_unit)

    with pytest.raises(ModbusTimeoutError):
        await device_class(mock_modbus_unit).async_update()

    assert counter.count == ATTEMPTS == 3


def test_tuning_constants():
    """The documented timeout and attempt count are what the code uses."""
    assert ATTEMPTS == 3
    assert REQUEST_TIMEOUT == 1.0


def test_register_ranges_are_pinned():
    """The readable ranges the meters answer are literal, not derived."""
    assert Power.register_ranges == ((0x3080, 0x308B),)
    assert PhaseBlock.register_ranges == ((0x3040, 0x305D),)


def test_sentinels_are_victrons_invalid_values():
    """Each type's unavailable value is its largest positive or all-ones value."""
    assert sentinels.UNAVAILABLE_UINT8 == 0xFF
    assert sentinels.UNAVAILABLE_INT8 == (0x7F,)
    assert sentinels.UNAVAILABLE_UINT16 == 0xFFFF
    assert sentinels.UNAVAILABLE_INT16 == (0x7FFF,)
    assert sentinels.UNAVAILABLE_UINT24 == 0xFFFFFF
    assert sentinels.UNAVAILABLE_INT24 == (0x7FFFFF,)
    assert sentinels.UNAVAILABLE_UINT32 == 0xFFFFFFFF
    assert sentinels.UNAVAILABLE_INT32 == (0x7FFFFFFF,)
