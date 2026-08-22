"""Runs service.main's self-check under pytest.

The self-check's body stays defined in service/main.py itself (see its
docstring) rather than being relocated here — it reassigns ~18 of that
module's own top-level names via three separate `global` statements
(`_model`, `PROFILE_PATH`, `STORIES_DIR`, the scrape functions,
`build_clone`/`build_design`/`voice_synth`, and more) so the FastAPI route
handlers under test see the swapped-in fakes. A `global X` inside a function
rebinds X in whichever module the function is *defined* in — moving the
function's text into this file would rebind this module's globals instead,
leaving route handlers to see stale real state with no test failure to flag
it. This thin wrapper is what actually makes it pytest-discoverable.
"""

from service.main import _self_check


def test_main_self_check():
    _self_check()
