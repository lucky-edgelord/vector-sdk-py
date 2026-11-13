import json

import httpx
import pytest

import vector
from conftest import GENERAL

from vector.ext.webhooks import WebhookStore, create_app


async def _setup(harness_factory, tmp_path, **kw):
    client = vector.Client()
    h = await harness_factory(client)
    store = WebhookStore(str(tmp_path / "w.db"))
    wh, token = store.create("CI", GENERAL, "c" * 64)
    app = create_app(client, store, admin_key="k", base_url="https://hooks.example", **kw)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return h, store, wh, token, http


async def test_execute_discord_payload(harness_factory, tmp_path):
    h, store, wh, token, http = await _setup(harness_factory, tmp_path)
    url = f"/api/webhooks/{wh.id}/{token}"
    r = await http.post(url, json={"content": "deploy done", "username": "CI", "embeds": [
        {"title": "Build #7", "description": "passed", "color": 0xff0000,
         "fields": [{"name": "Time", "value": "42s", "inline": True}, {"name": "Tests", "value": "99", "inline": True}]}]})
    assert r.status_code == 204
    sent = h.native.sent[-1]
    assert sent["channel"] == GENERAL and sent["text"].startswith("**CI**\ndeploy done")
    assert "### <color #59fcb3>**Build #7**</color>" in sent["text"] and "| Time | Tests |" in sent["text"]

    r = await http.post(url + "?wait=true", json={"content": "hi"})
    body = r.json()
    assert r.status_code == 200 and body["content"] == "hi" and body["channel_id"] == GENERAL and body["author"]["bot"]

    # edit then delete the message it sent
    mid = body["id"]
    r = await http.patch(f"{url}/messages/{mid}", json={"content": "hi (edited)"})
    assert r.status_code == 200 and r.json()["edited_timestamp"]
    assert (await http.delete(f"{url}/messages/{mid}")).status_code == 204
    assert (await http.patch(f"{url}/messages/{mid}", json={"content": "x"})).status_code == 404


async def test_auth_errors_limits_and_info(harness_factory, tmp_path):
    h, store, wh, token, http = await _setup(harness_factory, tmp_path)
    url = f"/api/webhooks/{wh.id}/{token}"
    assert (await http.post(f"/api/webhooks/{wh.id}/wrong", json={"content": "x"})).status_code == 401
    assert (await http.post("/api/webhooks/1/x", json={"content": "x"})).status_code == 404
    r = await http.post(url, json={})
    assert r.status_code == 400 and r.json()["code"] == 50006
    assert (await http.post(url, json={"content": "x" * 2001})).status_code == 400
    assert (await http.post(url, content=b"{nope", headers={"content-type": "application/json"})).status_code == 400
    info = (await http.get(url)).json()
    assert info["id"] == wh.id and info["channel_id"] == GENERAL and info["token"] is None
    # v10 prefix and rate limit (5 per 2s)
    codes = [(await http.post(f"/api/v10/webhooks/{wh.id}/{token}", json={"content": str(i)})).status_code
             for i in range(7)]
    assert codes[:5] == [204] * 5 and 429 in codes
    limited = await http.post(url, json={"content": "x"})
    assert limited.json()["message"] == "You are being rate limited." and "retry-after" in limited.headers


async def test_multipart_files_slack_and_github(harness_factory, tmp_path):
    h, store, wh, token, http = await _setup(harness_factory, tmp_path)
    url = f"/api/webhooks/{wh.id}/{token}"
    r = await http.post(url, data={"payload_json": json.dumps({"content": "report"})},
                        files={"files[0]": ("chart.png", b"\x89PNG", "image/png")})
    assert r.status_code == 204
    assert h.native.sent[-1]["file"] == "chart.png" and h.native.sent[-2]["text"] == "report"

    r = await http.post(url + "/slack", json={"text": "hello from slack", "attachments": [
        {"title": "Alert", "text": "disk full", "color": "#ff0000", "fields": [{"title": "Host", "value": "db1", "short": True}]}]})
    assert r.status_code == 204 and "hello from slack" in h.native.sent[-1]["text"] and "disk full" in h.native.sent[-1]["text"]

    push = {"repository": {"full_name": "o/r"}, "sender": {"login": "luck"}, "ref": "refs/heads/main",
            "compare": "https://x", "commits": [{"id": "abcdef123456", "message": "fix bug\n\nlong", "url": "https://c"}]}
    r = await http.post(url + "/github", json=push, headers={"x-github-event": "push"})
    assert r.status_code == 204 and "[o/r:main] 1 new commit" in h.native.sent[-1]["text"] and "fix bug" in h.native.sent[-1]["text"]
    n = len(h.native.sent)
    assert (await http.post(url + "/github", json={}, headers={"x-github-event": "watch"})).status_code == 204
    assert len(h.native.sent) == n  # ignored events post nothing


async def test_admin_api(harness_factory, tmp_path):
    h, store, wh, token, http = await _setup(harness_factory, tmp_path)
    assert (await http.post("/admin/webhooks", json={"channel_id": GENERAL})).status_code == 401
    auth = {"authorization": "Bearer k"}
    r = await http.post("/admin/webhooks", json={"channel_id": GENERAL, "name": "ops"}, headers=auth)
    made = r.json()
    assert r.status_code == 200 and made["url"] == f"https://hooks.example/api/webhooks/{made['id']}/{made['token']}"
    assert (await http.post(made["url"].replace("https://hooks.example", ""), json={"content": "via admin"})).status_code == 204
    assert len((await http.get("/admin/webhooks", headers=auth)).json()) == 2
    assert (await http.delete(f"/admin/webhooks/{made['id']}", headers=auth)).status_code == 204
    assert (await http.post(f"/api/webhooks/{made['id']}/{made['token']}", json={"content": "x"})).status_code == 404
    assert (await http.get("/health")).json()["ok"] is True
