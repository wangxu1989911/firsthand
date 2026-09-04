"""Firsthand — grounded duplicate/related request detection for issue intake.

Phase 0 (see the design doc, §4) ships the contracts and the local stack only:
the shapes in :mod:`firsthand.contracts` are treated as *fixed* by every later
track, and :mod:`firsthand.storage` keeps the databases behind them swappable.
"""

__version__ = "0.1.0"
