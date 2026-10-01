import asyncio
import json
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
        assert [model["id"] for model in result.json()["models"]] == ["2b", "9b"]
        assert result.json()["deployment"]["status"] == "stopped"


def test_settings_persist_and_cannot_change_during_deployment(tmp_path):
    studio = Studio(tmp_path)
    settings = studio.settings.model_copy(
        update={
            "port": 9001,
            "python_index_url": "https://pypi.tuna.tsinghua.edu.cn/simple",
            "torch_auto_backend": False,
        }
    )
    studio.save_settings(settings)
    assert load_settings(tmp_path).port == 9001
    assert len(load_settings(tmp_path).api_key) >= 16
    assert load_settings(tmp_path).python_index_url == settings.python_index_url
    assert load_settings(tmp_path).torch_auto_backend is False
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
        {"python_index_url": "http://mirror.test/simple"},
        {"python_index_url": "https://key:secret@mirror.test/simple"},
        {"python_index_url": "https://mirror.test/simple?token=secret"},
        {"python_index_url": "https://mirror.test/simple#fragment"},
        {"python_index_url": "https://mirror.test/with space"},
        {"python_index_url": "https://mirror.test/with\nnewline"},
        {"python_index_url": "https://mirror.test:invalid/simple"},
    ],
)
def test_invalid_settings_are_rejected(tmp_path, changes):
    with pytest.raises(ValueError):
        Settings.model_validate({"model_dir": str(tmp_path), **changes})


def test_existing_settings_get_python_source_defaults_and_custom_paths_work(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"model_dir": str(tmp_path)}))
    settings = load_settings(tmp_path)
    assert settings.python_index_url == "https://pypi.org/simple"
    assert settings.torch_auto_backend is True
    settings = Settings(model_dir=str(tmp_path), python_index_url="https://mirror.test/pypi/web/simple/")
    assert settings.python_index_url == "https://mirror.test/pypi/web/simple"


@pytest.mark.parametrize("auto_backend", [True, False])
def test_runtime_install_uses_selected_source_and_torch_mode(tmp_path, monkeypatch, auto_backend):
    studio = Studio(tmp_path)
    studio.settings.python_index_url = "https://pypi.tuna.tsinghua.edu.cn/simple"
    studio.settings.torch_auto_backend = auto_backend
    conflicting_env = {
        "UV_INDEX": "https://other.test/simple",
        "UV_EXTRA_INDEX_URL": "https://other.test/simple",
        "UV_INDEX_URL": "https://other.test/simple",
        "UV_DEFAULT_INDEX": "https://other.test/simple",
        "UV_FIND_LINKS": "https://other.test/wheels",
        "UV_NO_INDEX": "1",
        "UV_TORCH_BACKEND": "cpu",
        "UV_CONFIG_FILE": "/other/uv.toml",
    }
    for key, value in conflicting_env.items():
        monkeypatch.setenv(key, value)
    captured = {}

    class Installer:
        @property
        def stdout(self):
            async def output():
                yield b"Installed inference dependencies\n"

            return output()

        async def wait(self):
            return 0

    async def create_installer(*command, **kwargs):
        captured.update(command=command, env=kwargs["env"])
        return Installer()

    monkeypatch.setattr("studio.service.asyncio.create_subprocess_exec", create_installer)
    monkeypatch.setattr("studio.service.inference_installed", lambda: True)
    asyncio.run(studio._install())
    command = captured["command"]
    assert command[command.index("--default-index") + 1] == studio.settings.python_index_url
    assert "--no-config" in command
    assert ("--torch-backend" in command) is auto_backend
    if auto_backend:
        assert command[command.index("--torch-backend") + 1] == "auto"
    assert not (conflicting_env.keys() & captured["env"].keys())
    assert studio.runtime["status"] == "ready"
    assert any(studio.settings.python_index_url in entry["message"] for entry in studio.logs)


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
