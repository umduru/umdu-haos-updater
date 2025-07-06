"""Property-based tests for updater.is_newer."""

from __future__ import annotations

from hypothesis import given, strategies as st
from app.updater import is_newer


@given(
    major_a=st.integers(min_value=0, max_value=20),
    minor_a=st.integers(min_value=0, max_value=20),
    patch_a=st.integers(min_value=0, max_value=20),
    major_b=st.integers(min_value=0, max_value=20),
    minor_b=st.integers(min_value=0, max_value=20),
    patch_b=st.integers(min_value=0, max_value=20),
)
def test_is_newer_semver(major_a, minor_a, patch_a, major_b, minor_b, patch_b):
    v_a = f"{major_a}.{minor_a}.{patch_a}"
    v_b = f"{major_b}.{minor_b}.{patch_b}"

    expected = (major_a, minor_a, patch_a) > (major_b, minor_b, patch_b)
    assert is_newer(v_a, v_b) == expected