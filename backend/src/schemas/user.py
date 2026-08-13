"""Self-service profile and organization settings.

Separate from `schemas/auth.py`, which describes identity as the auth
system sees it. These are the narrow slices a signed-in user (or an
organization admin) is allowed to change about themselves.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdate(BaseModel):
    """What a user may change about their own account.

    Deliberately only the display name. `email` and `username` are
    identity: email is how Google sign-in matches the account, so
    letting a user rewrite it would let them take over a different
    identity or lock themselves out of their own. `is_active`,
    `registration_status` and role membership are administrative
    decisions, changed through the admin endpoints which check a
    permission this one does not require.
    """

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class OrganizationUpdate(BaseModel):
    """Organization-level settings an admin may change.

    `code` is excluded because it is a stable identifier referenced
    elsewhere, and renaming it silently would break those references.
    `plan` is excluded because it is a billing decision rather than a
    setting, and `is_active` because deactivating an organization is not
    something to do from a settings form.
    """

    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    domain: str | None = None
    is_active: bool
    plan: str
