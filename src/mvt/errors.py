from __future__ import annotations


class MVTError(Exception):
    code = "MVT_ERROR"
    exit_code = 2


class ContractError(MVTError):
    code = "CONTRACT_INVALID"
    exit_code = 3


class BuildError(MVTError):
    code = "BUILD_FAILED"
    exit_code = 4


class AuditRed(MVTError):
    code = "AUDIT_RED"
    exit_code = 5


class GovernanceError(MVTError):
    code = "GOVERNANCE_BLOCKED"
    exit_code = 6
