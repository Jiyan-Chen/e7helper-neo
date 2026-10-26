"""B14b：训练曲线页（不需要 torch）。"""

import json

from fastapi.testclient import TestClient

from e7helper.core.rta.train.watch import create_app


def _run(root, name, lines, status="running", partial=""):
    d = root / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"model": "transformer", "d": 64, "layers": 2, "secret": 1}), encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"status": status, "epoch": 1, "epochs": 30}), encoding="utf-8")
    (d / "metrics.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines) + partial, encoding="utf-8")


def test_watch_api(tmp_path):
    lines = [{"kind": "step", "frac": 0.5, "loss": 0.7}, {"kind": "step", "frac": 1.0, "loss": 0.69},
             {"kind": "val", "epoch": 1, "loss": 0.68}]
    _run(tmp_path, "tf-a", lines, partial='{"kind": "st')
    _run(tmp_path, "lr", lines[:1], status="done")
    (tmp_path / "empty").mkdir()  # 没有 metrics.jsonl 的目录不算
    client = TestClient(create_app(tmp_path))

    page = client.get("/")
    assert page.status_code == 200 and "RTA 训练曲线" in page.text

    runs = client.get("/api/runs").json()
    assert {r["name"] for r in runs["runs"]} == {"tf-a", "lr"}
    tf = next(r for r in runs["runs"] if r["name"] == "tf-a")
    assert tf["config"]["d"] == 64 and "secret" not in tf["config"] and tf["status"]["status"] == "running"
    assert tf["result"] is None

    m = client.get("/api/runs/tf-a/metrics").json()
    assert m["next"] == 3 and [x["kind"] for x in m["lines"]] == ["step", "step", "val"]  # 半行不返回
    m = client.get("/api/runs/tf-a/metrics?since=2").json()
    assert m["next"] == 3 and len(m["lines"]) == 1
    assert client.get("/api/runs/tf-a/metrics?since=9").json() == {"lines": [], "next": 9}
    assert client.get("/api/runs/nope/metrics").status_code == 404
    assert client.get("/api/runs/..%5Ctf-a/metrics").status_code == 404
