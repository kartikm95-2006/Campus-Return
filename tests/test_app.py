import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DATABASE": str(tmp_path / "test.db"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "ADMIN_EMAIL": "admin@campus.edu",
        "ADMIN_PASSWORD": "CampusAdmin123!",
    })
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, name="Riya Shah", email="riya@campus.edu"):
    return client.post("/register", data={"name": name, "email": email, "password": "testing123"}, follow_redirects=True)


def login(client, email, password="testing123"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def post_report(client, kind, title, description, category="Electronics", location="Library", event_date="2026-10-08", verification="A small star sticker under the case"):
    return client.post("/report", data={
        "kind": kind,
        "title": title,
        "category": category,
        "description": description,
        "location": location,
        "event_date": event_date,
        "verification_details": verification,
    }, follow_redirects=True)


def test_registration_and_invalid_password(client):
    response = client.post("/register", data={"name": "Riya", "email": "riya@campus.edu", "password": "short"}, follow_redirects=True)
    assert b"at least 8 characters" in response.data
    response = register(client)
    assert b"Your student account is ready" in response.data
    assert b"My activity" in response.data


def test_login_has_a_standalone_page_without_board_navigation(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Sign in to Campus Return" in response.data
    assert b"Back to the board" not in response.data
    assert b"Browse board" not in response.data
    assert b"What\xe2\x80\x99s out there" not in response.data
    assert b'<a class="brand" href="/">' not in response.data


def test_lost_report_suggests_found_match_and_keeps_clue_private(client):
    register(client)
    post_report(client, "lost", "Black Android phone", "Black phone with a cracked corner and clear protective case")
    post_report(client, "found", "Android phone found", "Android phone in a clear case, cracked corner near the screen")

    response = client.get("/items/1")
    assert b"Could this be yours?" in response.data
    assert b"Android phone found" in response.data
    assert b"star sticker" not in response.data


def test_claim_review_marks_returned_and_notifies_claimant(client):
    register(client, "Finder", "finder@campus.edu")
    post_report(client, "found", "Silver headphones", "Silver over-ear headphones in a black fabric pouch")
    client.post("/logout")
    register(client, "Claimant", "claimant@campus.edu")
    claim = client.post("/items/1", data={"details": "There is a blue fabric tag tied to the left side."}, follow_redirects=True)
    assert b"Claim submitted privately" in claim.data
    duplicate = client.post("/items/1", data={"details": "A second identifying detail about the headphones."}, follow_redirects=True)
    assert b"already submitted a claim" in duplicate.data

    login(client, "admin@campus.edu", "CampusAdmin123!")
    admin_page = client.get("/admin")
    assert b"Private report detail" in admin_page.data
    assert b"star sticker" in admin_page.data
    response = client.post("/admin/claims/1", data={"decision": "approved"}, follow_redirects=True)
    assert b"Claim approved" in response.data
    client.post("/logout")
    login(client, "claimant@campus.edu")
    dashboard = client.get("/my-activity")
    assert b"approved" in dashboard.data
    assert b"Arrange collection" in dashboard.data
    assert b"returned" in dashboard.data


def test_student_cannot_open_admin_dashboard(client):
    register(client)
    assert client.get("/admin").status_code == 403


def test_student_cannot_claim_their_own_or_lost_report(app, client):
    register(client)
    post_report(client, "lost", "Lost wallet", "Brown leather wallet with a library card")
    post_report(client, "found", "Found wallet", "Brown leather wallet found near the stairs")
    assert client.post("/items/1", data={"details": "It has a unique mark on the inside."}).status_code == 403
    assert client.post("/items/2", data={"details": "It has a unique mark on the inside."}).status_code == 403

    other_student = app.test_client()
    register(other_student, "Another student", "other@campus.edu")
    assert other_student.post("/items/1", data={"details": "It has a unique mark on the inside."}).status_code == 403


def test_search_filters_reports(client):
    register(client)
    post_report(client, "lost", "Green notebook", "Green notebook with chemistry notes inside", category="Books", location="Library")
    assert b"Green notebook" in client.get("/?q=chemistry&category=Books").data
    assert b"Green notebook" not in client.get("/?q=chemistry&category=Electronics").data
