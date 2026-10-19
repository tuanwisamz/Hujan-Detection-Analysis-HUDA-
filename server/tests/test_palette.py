import numpy as np
import pytest

from app.services import palette


def test_table_loads_universal_blue():
    dbz, rgba = palette._table()
    assert dbz.min() == -10 and dbz.max() >= 64
    assert (rgba[:, 3] > 0).all()


@pytest.mark.parametrize("value", [15, 20, 30, 35, 40, 45, 47, 50, 55, 60, 64])
def test_round_trip_within_1_dbz(value):
    img = palette.dbz_to_rgba(np.full((2, 2), float(value)), min_dbz=-32)
    decoded = palette.rgba_to_dbz(img)
    assert np.allclose(decoded, value, atol=1)


def test_transparent_is_no_echo():
    img = np.zeros((3, 3, 4), dtype=np.uint8)
    img[..., :3] = 200  # colour with alpha 0 still means nothing
    assert np.isnan(palette.rgba_to_dbz(img)).all()


def test_slightly_off_colours_still_decode():
    img = palette.dbz_to_rgba(np.array([[40.0]]), min_dbz=-32).astype(np.int16)
    img[..., :3] += 3  # PNG quantisation noise
    assert palette.rgba_to_dbz(img.clip(0, 255).astype(np.uint8))[0, 0] == pytest.approx(40, abs=1)


def test_marshall_palmer_thresholds_match_spec():
    # spec §6.2: 30 mm/h ≈ 47 dBZ, 10 mm/h ≈ 39 dBZ
    assert palette.dbz_to_rate(np.array([46.6]))[0] == pytest.approx(30, rel=0.03)
    assert palette.dbz_to_rate(np.array([39.0]))[0] == pytest.approx(10, rel=0.03)
    assert palette.dbz_to_rate(np.array([14.9, np.nan])).tolist() == [0, 0]


def test_rate_dbz_inverse():
    r = np.array([1.0, 10.0, 30.0, 65.0])
    assert np.allclose(palette.dbz_to_rate(palette.rate_to_dbz(r)), r, rtol=1e-3)
