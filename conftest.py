# Empty conftest.py at repo root.
# This tells pytest to add the repo root to sys.path, so `from collector...`
# imports work in tests. (Belt-and-suspenders alongside pyproject.toml.)
