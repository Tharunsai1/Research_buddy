"""Guards the guard: every path constant store.py writes through must be
covered by the isolated_store fixture.

This exists because one wasn't. LIBRARY_INDEX_FILE was added to store.py
without a matching entry in conftest.py's _STORE_DIRS/_STORE_FILES, so
test_remove_paper_drops_the_stale_library_embedding (test_store.py) wrote a
fake `[0.2] * 8` embedding straight into the real backend/data/library_index.json
— the user's actual 121-paper library, not a tmp dir. No test failed; it was
only caught by inspecting live search output and noticing one entry had 8
dimensions instead of nomic-embed-text's 768.

A module-level constant is easy to add and easy to forget to sandbox. This
test makes forgetting loud: it fails the moment a new *_FILE or *_DIR constant
appears in store.py without a matching fixture entry, instead of staying
silent while a future test corrupts real data the same way.
"""

from __future__ import annotations

import store
from tests.conftest import _STORE_DIRS, _STORE_FILES


def test_every_directory_constant_is_sandboxed():
    declared = {
        name for name in vars(store)
        if name.endswith("_DIR") and name != "DATA_DIR" and isinstance(getattr(store, name), type(store.DATA_DIR))
    }
    assert declared <= set(_STORE_DIRS), (
        f"store.py defines {declared - set(_STORE_DIRS)} but conftest's isolated_store "
        "fixture does not sandbox it — add it to _STORE_DIRS or a test can write to "
        "real backend/data/."
    )


def test_every_top_level_file_constant_is_sandboxed():
    declared = {
        name for name in vars(store)
        if name.endswith("_FILE") and isinstance(getattr(store, name), type(store.DATA_DIR))
    }
    assert declared <= set(_STORE_FILES), (
        f"store.py defines {declared - set(_STORE_FILES)} but conftest's isolated_store "
        "fixture does not sandbox it — add it to _STORE_FILES or a test can write to "
        "real backend/data/."
    )


def test_the_fixture_actually_redirects_every_declared_path(isolated_store, tmp_path):
    """Not just "is it listed" — does patching it actually point outside the
    real data directory."""
    real_data_dir = (store.__file__ and __import__("pathlib").Path(store.__file__).parent / "data")
    for name in _STORE_DIRS + _STORE_FILES:
        patched = getattr(isolated_store, name)
        assert str(tmp_path) in str(patched), f"{name} was not redirected into tmp_path"
        assert not str(patched).startswith(str(real_data_dir)), f"{name} still points at real data/"
