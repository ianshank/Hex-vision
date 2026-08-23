"""Test package marker.

Present so that same-named modules in sibling test directories (notably the
per-directory ``conftest.py`` files) resolve to distinct module paths. Without
it the type checker sees two modules both named ``conftest`` and stops.
"""
