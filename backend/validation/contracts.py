"""Compatibility imports for the relocated scientific result contracts."""
from nova.core.contracts import (
    CanonicalSolverResult,
    ConvergenceDiagnostics,
    ConvergenceInfo,
    OperatingPoint,
    PerformanceSummary,
    SolverIdentity,
    StrictModel,
)

__all__ = ["CanonicalSolverResult", "ConvergenceDiagnostics", "ConvergenceInfo",
           "OperatingPoint", "PerformanceSummary", "SolverIdentity", "StrictModel"]
