import pytest
import pytz
from freezegun import freeze_time

from runnel.utils import seconds_until


@freeze_time('1970-01-01 00:00:00')
@pytest.mark.parametrize(
    'spec, tz, expected',
    [
        ("* * * * *", None, 60),
        ("5 0 1 1 *", None, 5 * 60),
        ("* * * * *", pytz.UTC, 60),
        ("*/15 * * * *", pytz.UTC, 60 * 15),
        ("0 2 * * *", pytz.timezone('CET'), 60 * 60)  # It's 1am CET, so only 1 hour.
    ]
)
def test_seconds_until(spec, tz, expected):
    assert seconds_until(spec, tz) == expected
