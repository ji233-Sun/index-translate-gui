import hashlib
import threading

import httpx
import pytest

from studio.catalog import RemoteFile, fetch_manifest, safe_model_file, serialize_manifest
from studio.downloads import (
    DownloadPaused,
    download_file,
    file_matches,
    local_model,
    model_directory,
    partial_path,
)
from studio.settings import Settings, write_json

DATA = b"real checkpoint bytes for transfer tests"


def remote():
    return RemoteFile(
        "weights.safetensors", len(DATA), "https://source.test/weights", hashlib.sha256(DATA).hexdigest()
    )


@pytest.mark.parametrize("ignore_range", [False, True])
def test_resume_does_not_duplicate_bytes_when_mirror_ignores_range(tmp_path, ignore_range):
    file = remote()
    path = tmp_path / file.path
    partial_path(path, file).write_bytes(DATA[:8])

    def handle(request):
        assert request.headers["range"] == "bytes=8-"
        return (
            httpx.Response(200, content=DATA)
            if ignore_range
            else httpx.Response(
                206, content=DATA[8:], headers={"Content-Range": f"bytes 8-{len(DATA) - 1}/{len(DATA)}"}
            )
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        download_file(client, file, tmp_path, threading.Event(), lambda _: None)
    assert path.read_bytes() == DATA
    assert file_matches(path, file)
    assert not partial_path(path, file).exists()


def test_incorrect_range_and_checksum_never_promote_a_partial(tmp_path):
    file = remote()
    partial = partial_path(tmp_path / file.path, file)
    partial.write_bytes(DATA[:8])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                206, content=DATA[8:], headers={"Content-Range": f"bytes 0-{len(DATA) - 1}/{len(DATA)}"}
            )
        )
    ) as client:
        with pytest.raises(ValueError, match="续传范围"):
            download_file(client, file, tmp_path, threading.Event(), lambda _: None)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * len(DATA)))
    ) as client:
        with pytest.raises(ValueError, match="校验失败"):
            download_file(client, file, tmp_path, threading.Event(), lambda _: None)
    assert not (tmp_path / file.path).exists()


def test_pause_keeps_partial_and_retry_repairs_corruption(tmp_path):
    file = remote()
    cancel = threading.Event()
    cancel.set()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=DATA))) as client:
        with pytest.raises(DownloadPaused):
            download_file(client, file, tmp_path, cancel, lambda _: None)
        partial_path(tmp_path / file.path, file).write_bytes(b"x" * len(DATA))
        cancel.clear()
        download_file(client, file, tmp_path, cancel, lambda _: None)
    assert (tmp_path / file.path).read_bytes() == DATA


def test_new_manifest_cannot_reuse_completion_marker_for_old_content(tmp_path):
    settings = Settings(model_dir=str(tmp_path))
    directory = model_directory(settings, "2b")
    directory.mkdir()
    file = remote()
    (directory / file.path).write_bytes(DATA)
    write_json(directory / ".manifest.json", {"source": "modelscope", "files": serialize_manifest([file])})
    write_json(directory / ".complete.json", {"files": {file.path: file.identity}})
    assert local_model(settings, "2b")["status"] == "ready"
    file.sha256 = "0" * 64
    write_json(directory / ".manifest.json", {"source": "modelscope", "files": serialize_manifest([file])})
    assert local_model(settings, "2b")["status"] == "partial"


@pytest.mark.parametrize("name", ["../model", "/model.json", "x/../../model", "x\\model", "C:/model"])
def test_repository_paths_cannot_escape_model_directory(name):
    with pytest.raises(ValueError, match="不安全"):
        safe_model_file(name)


def test_incomplete_repository_is_not_downloadable(tmp_path):
    payload = {
        "sha": "fixed-revision",
        "siblings": [
            {"rfilename": "config.json", "size": 10, "blobId": "abc"},
            {"rfilename": "model.safetensors.index.json", "size": 10, "blobId": "def"},
        ],
    }
    settings = Settings(model_dir=str(tmp_path), source="huggingface")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ValueError, match="尚未提供完整模型权重"):
            fetch_manifest(client, "2b", settings)


@pytest.mark.parametrize("source", ["huggingface", "hf-mirror", "custom", "modelscope"])
def test_all_download_sources_use_content_revision_and_hash(tmp_path, source):
    names = ["config.json", "tokenizer_config.json", "model.safetensors"]
    payload = {
        "sha": "fixed-revision",
        "siblings": [
            {"rfilename": name, "size": len(DATA), "lfs": {"sha256": remote().sha256}} for name in names
        ],
    }
    if source == "modelscope":
        payload = {
            "Success": True,
            "Data": {
                "Files": [
                    {
                        "Path": name,
                        "Size": len(DATA),
                        "Sha256": remote().sha256,
                        "Revision": "fixed-revision",
                        "Type": "blob",
                    }
                    for name in names
                ]
            },
        }
    settings = Settings(model_dir=str(tmp_path), source=source, mirror_url="https://mirror.test")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        files = fetch_manifest(client, "2b", settings)
    assert len(files) == 3
    assert all("fixed-revision" in file.url and file.sha256 == remote().sha256 for file in files)
    expected = {
        "huggingface": "huggingface.co",
        "hf-mirror": "hf-mirror.com",
        "custom": "mirror.test",
        "modelscope": "modelscope.cn",
    }[source]
    assert httpx.URL(files[0].url).host == expected
    if source == "modelscope":
        assert httpx.URL(files[0].url).path.endswith("/repo")
        assert httpx.URL(files[0].url).params["FilePath"] == "config.json"
