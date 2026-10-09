import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_audio_keeps_transcript_when_analysis_fails(api_module, monkeypatch):
    api = api_module
    db = MagicMock()
    db.get_audio_recording.return_value = {"id": "rec", "userId": "owner", "courseId": "course", "storagePath": "audio/owner/course/input.mp3"}
    db.get_owned_course.return_value = {"id": "course", "userId": "owner", "title": "Course"}
    db.audio_job_exists.return_value = True
    monkeypatch.setattr(api, "db_client", db)
    audio = MagicMock()
    audio.transcribe_audio.return_value = "A recovered transcript explaining limits in sufficient detail."
    audio.analyze_transcript.side_effect = RuntimeError("synthetic provider failure")
    monkeypatch.setattr(api, "audio_agent", audio)
    assert api._run_audio_pipeline("rec", "course", file_bytes=b"fake audio", audio_ext="mp3") is False
    checkpoints = [call.args[1] for call in db.update_audio_recording.call_args_list]
    assert any(item.get("transcript") == audio.transcribe_audio.return_value for item in checkpoints)


def test_deleted_audio_job_never_calls_model(api_module, monkeypatch):
    db = MagicMock()
    db.get_audio_recording.return_value = {}
    db.audio_job_exists.return_value = False
    monkeypatch.setattr(api_module, "db_client", db)
    audio = MagicMock()
    monkeypatch.setattr(api_module, "audio_agent", audio)
    assert api_module._run_audio_pipeline("deleted", "course", file_bytes=b"fake", audio_ext="mp3") is False
    audio.transcribe_audio.assert_not_called()
    audio.analyze_transcript.assert_not_called()
    db.update_audio_recording.assert_not_called()


def test_reanalysis_recovers_image_only_document(api_module, monkeypatch):
    db = MagicMock()
    db.get_document.return_value = {"userId": "owner", "courseId": "course", "fileType": "pdf", "storagePath": "documents/owner/course/scan.pdf", "extractedText": ""}
    db.get_owned_course.return_value = {"userId": "owner", "title": "Course"}
    monkeypatch.setattr(api_module, "db_client", db)
    monkeypatch.setattr("src.utils.pdf_extract.pdf_to_image_uris", lambda data: ["data:image/png;base64,synthetic"])
    processor = MagicMock()
    processor.analyze_document.return_value = {"topics": ["Limits"]}
    monkeypatch.setattr(api_module, "doc_processor", processor)
    fake_path = MagicMock()
    fake_path.read_bytes.return_value = b"synthetic PDF"
    db.download_file_from_storage.return_value = fake_path
    assert api_module.reanalyze_document("scan", uid="owner")["status"] == "success"
    assert processor.analyze_document.call_args.kwargs["image_uris"]


def test_audio_runner_bounds_and_recovers(monkeypatch):
    from src.utils.job_runner import AudioJobRunner
    submitted = []
    fake_executor = MagicMock()
    fake_executor.submit.side_effect = lambda function, *args: submitted.append(args) or MagicMock()
    runner = AudioJobRunner(lambda: SimpleNamespace(get_pending_audio_jobs=lambda limit: [{"id": "one"}, {"id": "two"}]), lambda rec_id: None, max_workers=1, max_pending=1, executor=fake_executor)
    assert runner.submit("one") is True
    assert runner.submit("one") is False
    assert runner.submit("two") is False
    assert len(submitted) == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1/file.mp3", "https://[::1]/file", "http://user:password@example.com/x", "https://example.com:8080/x", "file:///private", "http://169.254.169.254/x"])
def test_media_url_rejects_local_credentials_and_ports(url):
    from src.utils.media_download import validate_media_url
    with pytest.raises(ValueError):
        validate_media_url(url)


def test_tex_rejects_file_input_and_shell_commands():
    from src.utils.compile_pdf import validate_tex_source
    for text in [r"\input{/private/key.json}", r"\openin1=secret", r"\write18{command}", r"\csname input\endcsname{secret}"]:
        with pytest.raises(ValueError):
            validate_tex_source(text)


def test_audio_temp_failure_releases_worker_slot(api_module, monkeypatch):
    db = MagicMock()
    db.get_audio_recording.return_value = {"userId": "owner", "courseId": "course"}
    db.audio_job_exists.return_value = True
    monkeypatch.setattr(api_module, "db_client", db)
    slots = MagicMock()
    slots.acquire.return_value = True
    monkeypatch.setattr(api_module, "_AUDIO_WORK_SLOTS", slots)
    monkeypatch.setattr("tempfile.mkdtemp", MagicMock(side_effect=OSError("synthetic full temp disk")))
    assert api_module._run_audio_pipeline("rec", "course") is False
    slots.release.assert_called_once()


def test_real_ffmpeg_accepts_audio_and_rejects_playlist_demuxer(api_module, tmp_path):
    import shutil
    import wave
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000)
    result = api_module._extract_audio_to_mp3(str(source))
    from pathlib import Path
    assert Path(result).stat().st_size > 0
    disguised = tmp_path / "disguised.mp3"
    disguised.write_text("ffconcat version 1.0\nfile 'tone.wav'\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        api_module._extract_audio_to_mp3(str(disguised))
    assert not disguised.with_suffix(".converted.mp3").exists()
