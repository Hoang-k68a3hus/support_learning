"""Tests for AI Data Studio boundaries and data-development contracts.

``unittest discover -s tests`` imports this directory as the top-level
``ai_data_studio`` package. Extend the package path so production submodules
remain importable instead of being shadowed by the test package.
"""

from pkgutil import extend_path


__path__ = extend_path(__path__, __name__)
