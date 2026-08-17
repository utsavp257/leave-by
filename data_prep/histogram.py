"""Travel times as histograms over whole minutes.

Everything in this project is a distribution, and distributions have to be
combined rather than summarised early. A journey to JFK by train is a wait for
the train, plus the ride, plus a walk, plus a wait for the AirTrain, plus the
AirTrain. Each of those has its own spread, and the question the project exists
to answer - how late might this get - depends on the spread of the total.

The temptation is to take the 90th percentile of each leg and add them up. That
is wrong, and wrong in a specific direction: it overstates the tail. Two legs
rarely have their bad days at the same moment, so the sum's 90th percentile sits
below the sum of the legs' 90th percentiles. `convolve` does it properly and
there is a test pinning the arithmetic.

Histograms rather than samples, for the same reason stringline uses them: the
counts stay small no matter how many trips go through them, they merge by
addition, and percentiles come out exact to the minute.

A histogram here is a plain list of counts, one entry per minute from 0. The
final entry means "this long or longer", so nothing is ever silently discarded
for being slow - which matters, because the slow trips are the point.
"""

from __future__ import annotations

MAX_MINUTES = 180
"""Three hours. Longer than any airport run that is still a single trip, and the
overflow bin keeps anything worse from vanishing."""


def from_samples(samples, max_minutes: int = MAX_MINUTES) -> list[int]:
    """Count durations in minutes into a fresh histogram."""
    counts = [0] * (max_minutes + 1)
    for value in samples:
        minutes = int(value)
        if minutes < 0:
            raise ValueError(f"negative duration: {value}")
        counts[min(minutes, max_minutes)] += 1
    return counts


def merge(a: list[int], b: list[int]) -> list[int]:
    """Combine two histograms of the same thing, measured separately."""
    if len(a) != len(b):
        raise ValueError(f"histogram lengths differ: {len(a)} and {len(b)}")
    return [x + y for x, y in zip(a, b)]


def total(counts: list[int]) -> int:
    """How many observations went into this histogram."""
    return sum(counts)


def percentile(counts: list[int], q: float) -> int:
    """The first minute at which the cumulative count reaches `q` of the total.

    This is the inverse of the empirical distribution function, taken from
    below, which is the reading a traveller wants: "leave this many minutes
    early and you arrive in time on q of days".
    """
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"quantile out of range: {q}")

    n = total(counts)
    if n == 0:
        raise ValueError("cannot take a percentile of an empty histogram")

    target = q * n
    seen = 0
    for minutes, count in enumerate(counts):
        seen += count
        if seen >= target:
            return minutes
    return len(counts) - 1


def mean(counts: list[int]) -> float:
    """Average duration in minutes. Reported alongside percentiles, never
    instead of them - the average is the number that hides the problem."""
    n = total(counts)
    if n == 0:
        raise ValueError("cannot take a mean of an empty histogram")
    return sum(minutes * count for minutes, count in enumerate(counts)) / n


def convolve(a: list[int], b: list[int]) -> list[int]:
    """The distribution of the sum of two independent legs.

    Truncated to the length of `a`, with the overflow gathered into the final
    bin so a long tail is capped rather than lost.

    Independence is an assumption, and on some pairs of legs it is a shaky one:
    a snowstorm delays the subway and the AirTrain together. Where the legs
    plainly share a cause, say so next to the number rather than pretending the
    convolution settles it.
    """
    if len(a) != len(b):
        raise ValueError(f"histogram lengths differ: {len(a)} and {len(b)}")

    size = len(a)
    out = [0] * size
    last = size - 1
    for i, count_a in enumerate(a):
        if count_a == 0:
            continue
        for j, count_b in enumerate(b):
            if count_b == 0:
                continue
            out[min(i + j, last)] += count_a * count_b
    return out
