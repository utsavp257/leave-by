"""Which origins are worth putting in front of a reader.

The trip records carry a few zone ids that are not neighbourhoods - the airports
themselves, and catch-alls for pickups the system could not place. Left in, they
produce nonsense rows like "JFK to JFK, 14 minutes" and unlabelled entries in
the picker, so they are filtered. The filter is small and easy to get subtly
wrong, hence the tests.
"""

from data_prep.zones import is_reportable

ZONES = {
    1: {"name": "Newark Airport", "borough": "EWR"},
    132: {"name": "JFK Airport", "borough": "Queens"},
    138: {"name": "LaGuardia Airport", "borough": "Queens"},
    161: {"name": "Midtown Center", "borough": "Manhattan"},
    264: {"name": "Unknown zone 264", "borough": "Unknown"},
    265: {"name": "Outside of NYC", "borough": "N/A"},
}


def test_a_real_neighbourhood_is_reportable():
    assert is_reportable(161, ZONES)


def test_the_airports_are_not_origins():
    # Otherwise airport-to-airport transfers show up as origins.
    assert not is_reportable(132, ZONES)
    assert not is_reportable(138, ZONES)
    assert not is_reportable(1, ZONES)


def test_placeholder_zones_are_excluded():
    assert not is_reportable(264, ZONES)
    assert not is_reportable(265, ZONES)


def test_an_unseen_id_is_not_reportable():
    assert not is_reportable(9999, ZONES)
