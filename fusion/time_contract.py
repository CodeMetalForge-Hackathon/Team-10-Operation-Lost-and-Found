"""Explicit clocks. These numbers are not interchangeable.

t_device_ms
    The node's own clock, milliseconds since that node's boot. The wire
    name remains ``t_ms``. It is not Unix time and it is not freshness.

t_recorded_s
    The original capture clock. ``tools/record_gateway.py`` and
    ``fusion/heatmap.py`` write Unix seconds, often fractional, into
    ``t_host``. After ingest that value lives only in ``t_recorded_s``.
    It is not freshness and it is not "now".

t_ingest_ms
    This host's clock when the line was accepted. Integer milliseconds.
    The dashboard field ``t_host`` is this same integer, kept so the
    current page does not have to be rewritten. Freshness and event age
    subtract two ingest clocks. They never subtract ``t_recorded_s``.

A recorder second and an ingest millisecond differ by about 1000x if
someone treats them as the same unit. ``as_unix_seconds`` is the only
conversion heatmap-style code should use.
"""

UNIX_MS_MIN = 100_000_000_000


def is_unix_milliseconds(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= UNIX_MS_MIN


def recorded_seconds(value):
    """Return a recorder ``t_host`` as Unix seconds, or None if it is not one.

    Integer Unix milliseconds are not recorder stamps. A float is seconds,
    which is what ``record_gateway.py`` writes.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) or not is_unix_milliseconds(value):
        return float(value)
    return None


def as_unix_seconds(value, default=None):
    """Convert recorder seconds or host milliseconds to Unix seconds.

    Values below ``UNIX_MS_MIN`` are already seconds, including the
    relative clocks used by ``fusion/bench.py``. Larger integers are
    host ingest milliseconds and are divided by 1000 here, not elsewhere.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if is_unix_milliseconds(value):
        return value / 1000.0
    return float(value)


def seconds_to_ingest_ms(seconds):
    return int(round(float(seconds) * 1000.0))


def ingest_ms_to_seconds(ingest_ms):
    return int(ingest_ms) / 1000.0


def ingest_milliseconds(now_ms):
    if isinstance(now_ms, bool) or not isinstance(now_ms, (int, float)):
        raise ValueError("host clock must be a number of milliseconds")
    return int(now_ms)


def freshness_age_ms(now_ms, ingest_ms):
    """Age of an accepted line. Both arguments are ingest milliseconds."""
    return ingest_milliseconds(now_ms) - ingest_milliseconds(ingest_ms)
