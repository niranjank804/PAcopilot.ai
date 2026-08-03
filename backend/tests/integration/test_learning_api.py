"""API tests for the TI corpus learning endpoints."""

import io
import zipfile

import pytest

from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_organization,
    create_user,
)

PROCESS = """601,100
602,"DATA - Load - {n}"
562,"NULL"
560,1
pMonth
561,1
2
572,4

# =====================================
# PURPOSE : Load ledger {n}
# =====================================
If( pMonth @= '' );
575,1
SaveDataAll;
"""


def exports(count: int, start: int = 0) -> list[tuple[str, bytes, str]]:
    return [
        (
            "files",
            (
                f"DATA - Load - {i}pro.txt",
                PROCESS.format(n=i).encode("utf-8"),
                "text/plain",
            ),
        )
        for i in range(start, start + count)
    ]


def zipped(count: int) -> bytes:
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        for i in range(count):
            archive.writestr(f"tm1/DATA - Load - {i}pro.txt", PROCESS.format(n=i))
        archive.writestr("tm1/readme.md", "not an export")

    return buffer.getvalue()


@pytest.mark.asyncio
async def test_learn_from_individual_exports(client, db_session):
    org, admin = await create_org_admin(db_session)

    response = await client.post(
        "/learning/corpus", files=exports(12), headers=auth_headers(admin)
    )

    assert response.status_code == 201
    data = response.json()["data"]

    assert data["processes_parsed"] == 12
    assert data["processes_failed"] == 0
    assert data["conventions_learned"] > 0


@pytest.mark.asyncio
async def test_learn_from_a_zip_archive(client, db_session):
    """TM1 exports arrive as a folder; a zip is the natural upload."""

    org, admin = await create_org_admin(db_session)

    response = await client.post(
        "/learning/corpus",
        files={"files": ("tm1.zip", zipped(15), "application/zip")},
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    data = response.json()["data"]

    assert data["processes_parsed"] == 15
    # The readme inside the archive is skipped, not treated as a process.
    assert all(r["filename"] != "readme.md" for r in data["rejected"])


@pytest.mark.asyncio
async def test_learned_standards_are_readable_afterwards(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post("/learning/corpus", files=exports(14), headers=headers)

    response = await client.get("/learning/standards", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]

    keys = {c["key"] for c in data["conventions"]}
    assert "no_inline_comments" in keys

    rule = next(c for c in data["conventions"] if c["key"] == "no_inline_comments")
    assert rule["support"] == 14
    assert rule["sample"] == 14


@pytest.mark.asyncio
async def test_standards_are_scoped_to_the_uploading_organization(
    client, db_session
):
    """The whole premise: one org's house style never reaches another.

    admin_b is fully permitted — the request is authorised and succeeds. It
    returns nothing because the conventions belong to another organization,
    which is a different guarantee from being refused.
    """

    org_a, admin_a = await create_org_admin(db_session)
    org_b, admin_b = await create_org_admin(db_session)

    await client.post(
        "/learning/corpus", files=exports(14), headers=auth_headers(admin_a)
    )

    response = await client.get(
        "/learning/standards", headers=auth_headers(admin_b)
    )

    assert response.status_code == 200
    assert response.json()["data"]["conventions"] == []

    # And org A still has its own, so this is isolation rather than nothing
    # having been stored at all.
    own = await client.get("/learning/standards", headers=auth_headers(admin_a))
    assert own.json()["data"]["conventions"]


@pytest.mark.asyncio
async def test_relearning_replaces_the_previous_corpus(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post("/learning/corpus", files=exports(20), headers=headers)
    await client.post("/learning/corpus", files=exports(9), headers=headers)

    response = await client.get("/learning/standards", headers=headers)
    rule = next(
        c
        for c in response.json()["data"]["conventions"]
        if c["key"] == "no_inline_comments"
    )

    assert rule["sample"] == 9


@pytest.mark.asyncio
async def test_report_renders_without_storing_anything(client, db_session):
    """A lead can review what would be learned before committing to it."""

    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    response = await client.post(
        "/learning/report", files=exports(14), headers=headers
    )

    assert response.status_code == 200
    assert "Company TM1 Standards Report" in response.json()["data"]["markdown"]

    stored = await client.get("/learning/standards", headers=headers)
    assert stored.json()["data"]["conventions"] == []


@pytest.mark.asyncio
async def test_upload_without_exports_is_rejected(client, db_session):
    org, admin = await create_org_admin(db_session)

    response = await client.post(
        "/learning/corpus",
        files={"files": ("notes.md", b"# not a process", "text/markdown")},
        headers=auth_headers(admin),
    )

    assert response.status_code == 422
    assert "No TurboIntegrator exports" in response.text


@pytest.mark.asyncio
async def test_learning_requires_write_permission(client, db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, organization_id=org.id)

    response = await client.post(
        "/learning/corpus", files=exports(3), headers=auth_headers(viewer)
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_learning_requires_authentication(client):
    response = await client.post("/learning/corpus", files=exports(3))

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_credential_bearing_exports_are_counted_not_stored(
    client, db_session
):
    org, admin = await create_org_admin(db_session)

    with_credentials = (
        '601,100\n602,"DATA - Load - Oracle"\n562,"ODBC"\n'
        '564,"svc_tm1_read"\n565,"encrypted-secret"\n'
        "572,1\nnX = 1;\n"
    )

    response = await client.post(
        "/learning/corpus",
        files=[
            ("files", ("a.pro", with_credentials.encode(), "text/plain")),
            *exports(3),
        ],
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    assert response.json()["data"]["files_with_stored_credentials"] == 1
    assert "svc_tm1_read" not in response.text
    assert "encrypted-secret" not in response.text


@pytest.mark.asyncio
async def test_a_small_upload_does_not_destroy_learned_standards(
    client, db_session
):
    """A trial upload must not wipe standards measured from a whole server.

    Replacing a standard with a better measurement is the point; replacing it
    with nothing because someone uploaded three files to see what happens is
    destruction, and the agents would silently fall back to generic TM1 style.
    """

    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post("/learning/corpus", files=exports(20), headers=headers)
    before = (await client.get("/learning/standards", headers=headers)).json()

    assert before["data"]["conventions"]

    response = await client.post(
        "/learning/corpus", files=exports(3, start=100), headers=headers
    )

    assert response.status_code == 201
    data = response.json()["data"]

    assert data["processes_parsed"] == 3
    assert data["replaced_existing"] is False
    assert "were kept" in data["note"]

    after = (await client.get("/learning/standards", headers=headers)).json()
    assert after["data"]["conventions"] == before["data"]["conventions"]


@pytest.mark.asyncio
async def test_a_large_upload_does_replace(client, db_session):
    """The guard must not block a genuine relearn."""

    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post("/learning/corpus", files=exports(20), headers=headers)
    response = await client.post(
        "/learning/corpus", files=exports(9, start=100), headers=headers
    )

    assert response.json()["data"]["replaced_existing"] is True

    after = await client.get("/learning/standards", headers=headers)
    rule = next(
        c
        for c in after.json()["data"]["conventions"]
        if c["key"] == "no_inline_comments"
    )
    assert rule["sample"] == 9
