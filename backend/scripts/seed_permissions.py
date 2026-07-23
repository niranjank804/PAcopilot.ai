import asyncio

from src.database.models.permission import Permission
from src.database.models.role_permission import RolePermission
from src.database.session import AsyncSessionLocal
from src.repositories.permission_repository import permission_repository
from src.repositories.role_permission_repository import (
    role_permission_repository,
)
from src.repositories.role_repository import role_repository

# Only resources that exist today. Future modules (TM1, AI, billing,
# reports, ...) add their own codes in their own migration/seed when
# those modules are actually built.
PERMISSIONS = [
    ("users.read", "View users."),
    ("users.write", "Create and update users."),
    ("users.delete", "Delete users."),
    ("roles.read", "View roles and permissions."),
    ("roles.write", "Create, update, and delete roles and their permissions."),
    ("organization.read", "View organization details."),
    ("organization.write", "Update organization details."),
    ("audit.view", "View audit logs."),
    ("ai.chat", "Use the AI chat assistant."),
    ("knowledge.read", "Search the knowledge base and ask grounded questions."),
    ("knowledge.write", "Upload and delete knowledge base documents."),
    ("tm1.read", "View TM1 connections and query cube/dimension metadata."),
    ("tm1.write", "Create and delete TM1 connections."),
    ("tm1.security.read", "View TM1 security groups and their members."),
    ("tm1.deploy", "Execute and roll back TM1 changes (rules, TI processes)."),
    ("monitoring.view", "View AI usage, tool, and TM1 status dashboards."),
]

READ_ONLY = [
    "users.read",
    "roles.read",
    "organization.read",
    "audit.view",
]

# ai.chat and knowledge.read are general capabilities, not admin actions,
# so every system role gets them (Super Admin/Organization Admin already
# get them via the full PERMISSIONS list below). knowledge.write follows
# the same admin-only pattern as roles.write/users.write. monitoring.view
# is operational visibility in the same spirit as audit.view (not the
# access-control sensitivity of tm1.security.read), so it's general too.
GENERAL_ROLE_PERMISSIONS = READ_ONLY + ["ai.chat", "knowledge.read", "monitoring.view"]

# tm1.read is *not* general like ai.chat/knowledge.read: TM1 connections
# hold live credentials to external enterprise systems, so only roles
# that plausibly do planning/analysis work get it - Viewer does not.
PLANNING_ROLE_PERMISSIONS = GENERAL_ROLE_PERMISSIONS + ["tm1.read"]

# tm1.deploy (executing writes against live TM1 servers) follows the same
# admin-only pattern as tm1.security.read: Super Admin/Organization Admin
# only, via the full PERMISSIONS list. Drafting changes needs tm1.write
# (also admin-only today); executing them additionally needs tm1.deploy —
# two distinct gates so a future role could draft without deploying.
# tm1.security.read is deliberately *not* added to any role list here -
# it's narrower than tm1.read (reading who-has-access-to-what, not just
# metadata), so only Super Admin/Organization Admin get it, via the full
# PERMISSIONS list below. Grant to other roles explicitly via the
# role-permission API if that's ever needed.

# NOTE: Planner/Analyst have no other dedicated resources yet, so they
# default to the same permission set as each other. Adjust via the
# role-permission API once those modules exist.
ROLE_PERMISSIONS = {
    "Super Admin": [code for code, _ in PERMISSIONS],
    "Organization Admin": [code for code, _ in PERMISSIONS],
    "Planner": PLANNING_ROLE_PERMISSIONS,
    "Analyst": PLANNING_ROLE_PERMISSIONS,
    "Viewer": GENERAL_ROLE_PERMISSIONS,
}


async def seed_permissions() -> None:
    async with AsyncSessionLocal() as db:
        codes_to_ids = {}

        for code, description in PERMISSIONS:
            existing = await permission_repository.get_by_code(db, code)

            if existing:
                print(f"Skipping existing permission: {code}")
                codes_to_ids[code] = existing.id
                continue

            permission = Permission(code=code, description=description)

            permission = await permission_repository.create(db, permission)

            codes_to_ids[code] = permission.id

            print(f"Created permission: {code}")

        for role_name, codes in ROLE_PERMISSIONS.items():
            role = await role_repository.get_system_role(db, role_name)

            if not role:
                print(
                    f"Skipping role-permission mapping for missing role: "
                    f"{role_name} (run seed_roles.py first)"
                )
                continue

            for code in codes:
                permission_id = codes_to_ids[code]

                existing = await role_permission_repository.get_by_role_and_permission(
                    db,
                    role.id,
                    permission_id,
                )

                if existing:
                    continue

                role_permission = RolePermission(
                    role_id=role.id,
                    permission_id=permission_id,
                )

                await role_permission_repository.create(db, role_permission)

                print(f"Granted {code} to {role_name}")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_permissions())
