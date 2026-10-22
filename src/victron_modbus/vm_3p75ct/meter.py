"""Grid connection totals: energy counters, PE-N voltage and frequency."""

from modbus_connection.model import gauge, uint32

from .._energy_meter import RegisterBlock, fine_frequency
from ..sentinels import (
    UNAVAILABLE_INT16,
    UNAVAILABLE_UINT16,
    UNAVAILABLE_UINT32,
)


class Meter(RegisterBlock):
    """Totals across all three phases, read from the holding registers."""

    total_forward_energy = uint32(
        0x3034, scale=0.01, nan=UNAVAILABLE_UINT32, unit="kWh"
    )
    """Total energy imported from the grid."""

    total_reverse_energy = uint32(
        0x3036, scale=0.01, nan=UNAVAILABLE_UINT32, unit="kWh"
    )
    """Total energy exported to the grid."""

    voltage_pen = gauge(0x3033, 0.01, nan=UNAVAILABLE_INT16, unit="V")
    """Voltage between PE and neutral."""

    frequency = gauge(0x3032, 0.01, signed=False, nan=UNAVAILABLE_UINT16, unit="Hz")
    """Grid frequency, in 0.01 Hz."""

    frequency_fine = fine_frequency()
    """Grid frequency, in 0.001 Hz; ``None`` if the meter's firmware lacks it."""
