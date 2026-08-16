from synthetic_data_platform.harbor_api import HttpHarborApiClient


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_submit_job_posts_input_datasets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict, timeout: float) -> FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"id": "job-1"})

    monkeypatch.setattr("synthetic_data_platform.harbor_api.httpx.post", fake_post)

    job_id = HttpHarborApiClient("http://harbor-api", timeout_sec=3).submit_job(
        {"job_name": "job-1"},
        input_datasets=[
            {
                "name": "dataset-a",
                "uri": "cos://harbor-datasets/datasets/a.tar.gz",
            }
        ],
    )

    assert job_id == "job-1"
    assert captured["url"] == "http://harbor-api/jobs"
    assert captured["timeout"] == 3
    assert captured["json"] == {
        "job_config": {"job_name": "job-1"},
        "input_datasets": [
            {
                "name": "dataset-a",
                "uri": "cos://harbor-datasets/datasets/a.tar.gz",
            }
        ],
    }
