"""The device object shared by every three-phase Victron energy meter.

Each meter model only differs in its register map (its ``Meter`` and ``Phase``
components); how the device is identified and polled, and where it reports its
power, is the same for all of them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING

from modbus_connection import ModbusTimeoutError
from modbus_connection.model import (
    Component,
    ComponentGroup,
    Device,
    NumberField,
    UpdateReport,
    gauge,
    int32,
    integer,
    read_optional,
    string,
)

from .sentinels import UNAVAILABLE_INT32, UNAVAILABLE_UINT16

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit
    from modbus_connection.model import Raw

# The polled sub-systems, as named in an ``UpdateReport``. The three phases are
# read together, so they succeed or fail together as ``"phases"``.
SUB_SYSTEMS = ("power", "meter", "phases")

# Power changes from moment to moment; the rest (voltage, current, energy
# counters, frequency) changes slowly. Polling them apart keeps a fast poll to
# the few registers worth reading that often.
FAST_SUB_SYSTEMS = ("power",)
SLOW_SUB_SYSTEMS = ("meter", "phases")

# Seconds to wait for an answer. Modbus/UDP never retransmits, so a lost
# datagram would otherwise stall the poll for the link's 10 s default; a meter
# on the local network answers within milliseconds.
REQUEST_TIMEOUT = 1.0

# How often a request is tried before its timeout is reported. A meter reached
# over Wi-Fi can lose a quarter of its datagrams, and setup needs a dozen
# requests in a row; without a retry that rarely completes.
ATTEMPTS = 3


def configure_unit(unit: ModbusUnit) -> None:
    """Set up a unit for talking to a Victron energy meter."""
    unit.require_timeout(REQUEST_TIMEOUT)


async def retry_lost[T](read: Callable[[], Awaitable[T]]) -> T:
    """Run ``read``, trying again when a request or its answer was lost.

    The last attempt's timeout is raised. Other errors are not retried: a
    refusal or a dropped connection would only repeat.
    """
    for _ in range(ATTEMPTS - 1):
        try:
            return await read()
        except ModbusTimeoutError:
            pass
    return await read()


class RegisterBlock(Component):
    """A component that only reads the registers it declares.

    The meters answer their register map in blocks, and reject a request that
    crosses from one block into the next. Where the readable ranges aren't
    declared, read nothing that isn't needed.
    """

    # Measured from the last register read, so 1 merges adjacent fields only.
    max_gap = 1


class PhaseBlock(RegisterBlock):
    """The per-phase registers, which every model answers as one block.

    Reading the registers between the fields too (line-to-line voltage, power
    factor and the current register the model doesn't use) puts all three
    phases in one request. Checked on a VM-3P75CT and a VM-3P5A.
    """

    register_ranges = ((0x3040, 0x305D),)


def fine_frequency() -> NumberField[float]:
    """The grid frequency in mHz resolution, at 0x303E.

    Read by meters whose firmware provides it; see ``EnergyMeter``.
    """
    return gauge(0x303E, 0.001, signed=False, nan=UNAVAILABLE_UINT16, unit="Hz")


class _FineFrequencyProbe(RegisterBlock):
    """Reads only the fine frequency, to learn whether the meter has it."""

    frequency_fine = fine_frequency()


class Config(RegisterBlock):
    """How the meter is installed."""

    phase_config = integer(0x2000, signed=False)
    """Which phases are connected; see ``EnergyMeter.connected_phases``."""


# Phase configuration (register 0x2000) -> the phases it connects, as Victron's
# own driver reads it: single phase on L1, L2 or L3, three phases, or L1 + L2.
_PHASES_BY_CONFIG: dict[int, tuple[int, ...]] = {
    0: (1,),
    1: (2,),
    2: (3,),
    3: (1, 2, 3),
    4: (1, 2),
}
ALL_PHASES = (1, 2, 3)


class Power(RegisterBlock):
    """Active power, in total and per phase; positive while importing."""

    # Includes the L1 and L2 apparent power between the fields, so the power is
    # one request.
    register_ranges = ((0x3080, 0x308B),)

    total = int32(0x3080, nan=UNAVAILABLE_INT32, unit="W")
    """Total active power across all phases."""

    l1 = int32(0x3082, nan=UNAVAILABLE_INT32, unit="W")
    """Active power on L1."""

    l2 = int32(0x3086, nan=UNAVAILABLE_INT32, unit="W")
    """Active power on L2."""

    l3 = int32(0x308A, nan=UNAVAILABLE_INT32, unit="W")
    """Active power on L3."""


class Info(RegisterBlock):
    """Product identification, common to every Victron Modbus device."""

    product_id = integer(0x1000, signed=False)
    """Victron product ID, e.g. ``0xA1B1`` for a VM-3P75CT."""

    serial_number = string(0x1001, 8)
    """Serial number."""

    hardware_version = integer(0x100B, signed=False, nan=UNAVAILABLE_UINT16)
    """Hardware revision; ``None`` if the device doesn't report one."""


class EnergyMeter[M: Component, P: Component](Device):
    """A three-phase energy meter reached through a ``ModbusUnit``."""

    def __init__(
        self,
        unit: ModbusUnit,
        meter: type[M],
        phase: type[P],
        *,
        info: Info | None = None,
    ) -> None:
        """Wrap ``unit``; pass ``info`` if the identification was read already."""
        super().__init__(unit)
        configure_unit(unit)

        # Sub-systems, each a Component. The three phases share one pooled read.
        self.info = Info(unit) if info is None else info
        # Read at setup; None until then, and if the meter doesn't have it.
        self.config: Config | None = None
        self.power = Power(unit)
        self.meter: M = meter(unit)
        self.phase_1: P = phase(unit, index=1)
        self.phase_2: P = phase(unit, index=2)
        self.phase_3: P = phase(unit, index=3)
        self.phases = ComponentGroup(unit, [self.phase_1, self.phase_2, self.phase_3])

    @property
    def connected_phases(self) -> tuple[int, ...]:
        """The phases the meter is connected to: 1 to 3, for L1 to L3.

        The readings of the other phases are not read and stay ``None``: a
        meter reports an unused phase with all bits set (for example -0.01 V),
        which would read as a value. A meter that doesn't say, or says
        something unknown, is taken as three-phase.
        """
        if self.config is None or self.config.phase_config is None:
            return ALL_PHASES
        return _PHASES_BY_CONFIG.get(self.config.phase_config, ALL_PHASES)

    async def _async_setup(self) -> None:
        """Read what never changes: the identification, and what the meter has.

        A meter model that declares ``frequency_fine`` only has it with recent
        enough firmware, and may reject a whole read that touches it otherwise.
        Try it once on its own, and stop reading it if the meter refuses.
        """
        if self.info.product_id is None:
            await retry_lost(self.info.async_update)
        self.config = await retry_lost(lambda: read_optional(Config(self.modbus_unit)))
        fields = self.meter.resolved_fields
        if "frequency_fine" in fields and (
            await retry_lost(
                lambda: read_optional(_FineFrequencyProbe(self.modbus_unit))
            )
            is None
        ):
            self.meter.restrict_fields(
                name for name in fields if name != "frequency_fine"
            )
        # Nothing is awaited from here on, so a retried setup never restricts twice.
        connected = self.connected_phases
        self.power.restrict_fields(["total", *(f"l{n}" for n in connected)])
        if connected != ALL_PHASES:
            phases = (self.phase_1, self.phase_2, self.phase_3)
            self.phases = ComponentGroup(
                self.modbus_unit, [phases[n - 1] for n in connected]
            )

    async def async_update(self, names: Iterable[str] = SUB_SYSTEMS) -> UpdateReport:
        """Refresh the named sub-systems; all of them by default.

        Pass ``FAST_SUB_SYSTEMS`` and ``SLOW_SUB_SYSTEMS`` to poll power more
        often than the rest.

        Over UDP a lost datagram shows up as a timeout, so a sub-system that
        times out is read again, up to ``ATTEMPTS`` times in all. A device that
        answers nothing therefore takes ``ATTEMPTS`` timeouts to give up on.
        The bound is per sub-system that is read: when several sub-systems each
        time out in turn, the total is longer. A caller that polls
        the sub-systems separately (fast and slow) gets the bound on each poll.

        Setup runs first, once, outside the retry loop, and has its own
        retries; a device that is dead from the start raises
        ``ModbusTimeoutError`` from it.
        """
        pending = list(names)
        report = UpdateReport()
        # Set up before the retry loop: setup retries its own reads, and
        # repeating it per attempt would multiply the timeouts on a dead device.
        await self.async_ensure_setup()
        for _ in range(ATTEMPTS - 1):
            try:
                report = await self.async_poll(pending, report)
            except ModbusTimeoutError:
                # Nothing had answered yet, so the whole poll is tried again.
                continue
            pending = [
                name
                for name, error in report.failed.items()
                if isinstance(error, ModbusTimeoutError)
            ]
            if not pending:
                return report
            # Read only what timed out; the rest of the report stands.
            report = UpdateReport(
                updated=set(report.updated),
                failed={n: e for n, e in report.failed.items() if n not in pending},
            )
        # The last attempt: whatever times out now is reported.
        return await self.async_poll(pending, report)

    async def async_read_raw(self, names: Iterable[str] = SUB_SYSTEMS) -> Raw:
        """Every register this device reads, undecoded - for diagnostics."""
        return await super().async_read_raw(("info", "config", *names))
