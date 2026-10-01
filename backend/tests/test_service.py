import socket

import pytest
from fastapi.testclient import TestClient

from studio.service import Studio, TranslationInput, create_control, translation_prompt
from studio.settings import Settings, load_settings


def test_control_is_separate_and_requires_its_own_secret(tmp_path):
    studio = Studio(tmp_path)
    with TestClient(create_control(studio, "control-secret")) as client:
        assert client.get("/status").status_code == 401
        assert (
            client.get("/status", headers={"Authorization": "Bearer " + studio.settings.api_key}).status_code
            == 401
        )
        result = client.get("/status", headers={"x-studio-token": "control-secret"})
        assert result.status_code == 200
        assert len(result.json()["models"]) == 3
        assert result.json()["deployment"]["status"] == "stopped"


def test_settings_persist_and_cannot_change_during_deployment(tmp_path):
    studio = Studio(tmp_path)
    settings = studio.settings.model_copy(update={"port": 9001})
    studio.save_settings(settings)
    assert load_settings(tmp_path).port == 9001
    assert len(load_settings(tmp_path).api_key) >= 16
    studio.deployment["status"] = "running"
    with pytest.raises(ValueError, match="停止"):
        studio.save_settings(settings)


@pytest.mark.parametrize(
    "changes",
    [
        {"port": 80},
        {"api_key": "short"},
        {"model_dir": "relative"},
        {"mirror_url": "http://mirror.test"},
        {"mirror_url": "https://key:secret@mirror.test"},
    ],
)
def test_invalid_settings_are_rejected(tmp_path, changes):
    with pytest.raises(ValueError):
        Settings.model_validate({"model_dir": str(tmp_path), **changes})


def test_port_conflict_reported_before_loading_weights(tmp_path, monkeypatch):
    studio = Studio(tmp_path)
    studio.runtime["status"] = "ready"
    monkeypatch.setattr("studio.service.local_model", lambda *_: {"status": "ready"})
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        studio.settings.port = occupied.getsockname()[1]
        with pytest.raises(ValueError, match="端口"):
            studio.start_model("2b")
    assert studio.deployment["status"] == "stopped"


def test_official_translation_prompt_and_custom_constraints():
    prompt = translation_prompt(TranslationInput(text="你好", target="en"))
    assert prompt == "请将以下文本翻译为英语，直接输出翻译结果，不要进行任何解释。\n\n你好"
    assert "中文文本翻译为日语" in translation_prompt(TranslationInput(text="你好", source="zh", target="ja"))
    assert "保留 JSON" in translation_prompt(TranslationInput(text="你好", instruction="保留 JSON"))
