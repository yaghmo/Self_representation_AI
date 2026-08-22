"""Runs service.main's self-check under pytest.

Stays defined in service/main.py, not relocated here — it reassigns ~18 of
that module's own top-level names via `global`, which only rebinds correctly
in the module it's defined in. This is just the pytest-discoverable wrapper.
"""

from service.main import _self_check


def test_main_self_check():
    _self_check()
