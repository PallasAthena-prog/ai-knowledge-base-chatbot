"""End-to-end tests through the HTTP API (needs the packages from requirements.txt)."""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from support import FAQ  # noqa: E402

TOKEN = "test-admin-token"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDINGS", "off")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LOAD_SAMPLE_DOCS", "false")
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    from app import config

    config.get_settings.cache_clear()
    import app.main as main

    main = importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client
    config.get_settings.cache_clear()


def events(body: str):
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def upload(client, name, data, content_type="text/markdown", token=TOKEN):
    headers = {"X-Admin-Token": token} if token else {}
    return client.post("/api/documents", files=[("files", (name, data, content_type))], headers=headers)


def test_health(client):
    health = client.get("/api/health").json()
    assert health["llm"]["enabled"] is False
    assert health["retrieval"]["mode"] == "keyword"
    assert health["uploads_need_token"] is True


def test_upload_needs_the_admin_token(client):
    assert upload(client, "faq.md", FAQ.read_bytes(), token=None).status_code == 401
    assert upload(client, "faq.md", FAQ.read_bytes(), token="wrong").status_code == 401


def test_full_flow(client):
    res = upload(client, FAQ.name, FAQ.read_bytes())
    assert res.status_code == 200
    result = res.json()["results"][0]
    doc = result["document"]
    assert doc["file_type"] == "md" and doc["chunk_count"] > 0

    bad = upload(client, "notes.exe", b"MZ", "application/octet-stream").json()["results"][0]
    assert "supported" in bad["error"]

    docs = client.get("/api/documents").json()["documents"]
    assert [d["id"] for d in docs] == [doc["id"]]

    page = client.get(f"/api/documents/{doc['id']}/pages/1").json()
    assert "Salesforce" in page["text"]
    original = client.get(f"/api/documents/{doc['id']}/file")
    assert original.status_code == 200 and original.content == FAQ.read_bytes()

    chat = client.post("/api/chat", json={"message": "Which tools does Northwind connect to?"})
    assert chat.status_code == 200
    assert chat.headers["content-type"].startswith("text/event-stream")
    stream = events(chat.text)
    assert stream[0][0] == "status" and stream[-1][0] == "final"
    final = stream[-1][1]
    assert final["mode"] == "quotes" and final["citations"]

    scoped = client.post("/api/chat", json={"message": "free trial", "document_ids": []})
    assert events(scoped.text)[-1][1]["mode"] == "none"

    assert client.post("/api/feedback", json={"question": "q", "answer": "a", "rating": 1}).json() == {"ok": True}
    stats = client.get("/api/stats").json()
    assert stats["questions"] == 2 and stats["feedback_up"] == 1

    assert client.delete(f"/api/documents/{doc['id']}").status_code == 401
    assert client.delete(f"/api/documents/{doc['id']}", headers={"X-Admin-Token": TOKEN}).status_code == 200
    assert client.get("/api/documents").json()["documents"] == []
    assert client.get(f"/api/documents/{doc['id']}/pages/1").status_code == 404


def test_validation(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.get("/api/documents/not-an-id/file").status_code == 404
    assert client.post("/api/feedback", json={"question": "q", "answer": "a", "rating": 5}).status_code == 422


def test_frontend_is_served(client):
    assert "Knowledge Base" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert "kbw-launcher" in client.get("/widget.js").text
