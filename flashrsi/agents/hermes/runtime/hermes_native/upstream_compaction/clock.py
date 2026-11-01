"""Clock boundary, replaceable by deterministic parity fixtures."""
import time as _time

def time():
    return _time.time()

def monotonic():
    return _time.monotonic()
