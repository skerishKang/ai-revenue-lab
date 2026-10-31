"""Content-rule contract for the PADIEM Parliament AI (#6061).

The research under #6014 established one operative fact for engineering: a
country code alone does not determine what a member may initiate, who has to
approve it, which citation coordinates are required, or which effective date
must be checked. Those answers vary by **institution tier** within a country,
and inside Korea and the United States they vary by the rules each individual
council adopts for itself.

This module is the single place where those researched values are declared, so
that a later feature (templates, terminology, citation verification, role
workflows) can consult one authority instead of re-deriving the law in view
code or prompt strings.

Three deliberate properties:

1. **Fail-closed.** An unregistered (country, tier, document kind) returns a
   record whose verification state is ``UNVERIFIED`` and whose fields are empty
   collections. Nothing is invented for a key we have not researched.
2. **No forced approver.** Approval requirements describe what the researched
   rules say about the *document*, never a mandate that a second human exists.
   Korean and US local evidence shows members who draft and approve alone.
3. **Sourced or flagged.** Every verified field carries at least one primary
   source with an access date. Unverified fields are listed, not hidden.

No runtime path imports this module yet. It is a contract and a data authority,
not a wired feature.
"""
from __future__ import annotations

from .contract import (
    ApprovalBasis,
    Country,
    DocumentKind,
    InstitutionTier,
    ParliamentRule,
    Source,
    StaffingModel,
    Unverified,
    Verification,
    WorkflowStep,
    approver_required,
    registered_keys,
    rule_for,
    rules_for_country,
    staffing_for,
    unresolved_keys,
    workflow_steps,
)

from . import mappings as _mappings  # registers the researched records

__all__ = [
    "ApprovalBasis",
    "Country",
    "DocumentKind",
    "InstitutionTier",
    "ParliamentRule",
    "Source",
    "StaffingModel",
    "Unverified",
    "Verification",
    "WorkflowStep",
    "approver_required",
    "registered_keys",
    "rule_for",
    "rules_for_country",
    "staffing_for",
    "unresolved_keys",
    "workflow_steps",
]
