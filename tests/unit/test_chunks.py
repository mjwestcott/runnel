import pytest

from runnel.utils import chunks


@pytest.mark.parametrize(
    'seq, n, expected', [
        ([1, 2, 3, 4, 5], 1, [[1, 2, 3, 4, 5]]),
        ([1, 2, 3, 4, 5], 2, [[1, 2, 3], [4, 5]]),
        ([1, 2, 3, 4, 5], 3, [[1, 2], [3, 4], [5]]),
        ([1, 2, 3, 4, 5], 4, [[1, 2], [3], [4], [5]]),
        ([1, 2, 3, 4, 5], 5, [[1], [2], [3], [4], [5]]),
        ([1, 2, 3, 4, 5], 6, [[1], [2], [3], [4], [5], []]),
    ]
)
def test_chunks(seq, n, expected):
    assert list(chunks(seq, n)) == expected
