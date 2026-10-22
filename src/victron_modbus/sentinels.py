"""Victron Modbus raw values that represent unavailable measurements.

A device reports a reading it doesn't have as the invalid value of the
register's type: the largest positive value for a signed register and all bits
set for an unsigned one.
"""

UNAVAILABLE_UINT8 = 0xFF
UNAVAILABLE_INT8 = (0x7F,)
UNAVAILABLE_UINT16 = 0xFFFF
UNAVAILABLE_INT16 = (0x7FFF,)
UNAVAILABLE_UINT24 = 0xFFFFFF
UNAVAILABLE_INT24 = (0x7FFFFF,)
UNAVAILABLE_UINT32 = 0xFFFFFFFF
UNAVAILABLE_INT32 = (0x7FFFFFFF,)
