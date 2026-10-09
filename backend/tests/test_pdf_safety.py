"""PDF compilation policy and the lifecycle of owned temporary artifacts."""
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.utils import compile_pdf


@pytest.fixture(autouse=True)
def local_temporary_root(tmp_path, monkeypatch):
    # The desktop sandbox's default Windows TEMP may not permit file writes.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


GOOD_TEX = r"""\documentclass[11pt,a4paper]{article}
\usepackage{amsmath,amssymb,tikz,verbatim,xcolor,eso-pic}
\usepackage[margin=2cm]{geometry}
\begin{document}
An exam: $\int_0^1 x^2 dx$.
\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}
\begin{verbatim}print('Hello')\end{verbatim}
\end{document}"""


@pytest.mark.parametrize("payload", [
    r"\input{/private/secret}", r"\include{secret}", r"\openin1=secret",
    r"\read1 to\data", r"\openout1=target", r"\write18{echo unsafe}",
    r"\csname input\endcsname{secret}", r"\catcode`\!=0 !input{secret}",
    r"\scantokens{unsafe}", r"^^5cinput{secret}", r"\directlua{os.execute('x')}",
    r"\special{psfile=secret}", r"\pdfobj file{secret}",
    r"\documentclass{../malicious}", r"\usepackage{/private/malicious}",
    r"\usepackage{\injected}", r"\usepackage{catchfile}",
    r"\RequirePackage{shellesc}", r"\includegraphics{secret}",
    r"\setmainfont[Path=/private/]{secret.ttf}",
    r"\input_secret", r"\setmainfont{C:/private/font.ttf}",
    r"\documentstyle[../malicious]{article}",
    r"\usetikzlibrary{../../malicious}", r"\tcbuselibrary{\injected}",
    r"\newfontfamily{\arabicfont}{C:/private/font.ttf}",
])
def test_rejects_files_shell_and_obfuscated_tex(payload):
    validate = getattr(compile_pdf, "validate_tex_source", None)
    assert callable(validate), "TeX source validation must exist"
    with pytest.raises(ValueError):
        validate(GOOD_TEX + payload)


def test_generated_math_tikz_code_and_system_fonts_remain_allowed():
    validate = getattr(compile_pdf, "validate_tex_source", None)
    assert callable(validate), "TeX source validation must exist"
    validate(GOOD_TEX)
    validate(GOOD_TEX + r"\usetikzlibrary{arrows.meta,calc,positioning}")
    validate(GOOD_TEX.replace(r"\usepackage{amsmath,amssymb,tikz,verbatim,xcolor,eso-pic}",
        r"\usepackage{fontspec,polyglossia}\newfontfamily\arabicfont[Script=Arabic]{Arial}"))


def test_unicode_preamble_has_ordered_system_font_fallbacks_and_clear_failure():
    responses = _responses()
    preamble = getattr(responses, "unicode_font_preamble", None)
    assert callable(preamble), "Portable Arabic preamble must exist"
    rendered = "\n".join(preamble())
    # These are output choices required by the supported export contract.
    position = -1
    for font in ("Arial", "Amiri", "Noto Naskh Arabic", "DejaVu Sans"):
        marker = r"\IfFontExistsTF{" + font + "}"
        next_position = rendered.find(marker)
        assert next_position > position
        position = next_position
        assert r"\newfontfamily\arabicfont[Script=Arabic]{" + font + "}" in rendered
    assert r"\PackageError{Mudaris}{No supported Arabic font is installed}" in rendered
    compile_pdf.validate_tex_source(r"\documentclass{article}" + rendered + r"\begin{document}\textarabic{مرحبا}\end{document}")


def test_unicode_preamble_is_independent_between_documents():
    responses = _responses()
    preamble = getattr(responses, "unicode_font_preamble", None)
    assert callable(preamble), "Portable Arabic preamble must exist"
    first = preamble()
    first.append(r"\input{unsafe}")
    compile_pdf.validate_tex_source("\n".join(preamble()))


def test_invalid_source_never_reaches_compiler(tmp_path, monkeypatch):
    tex = tmp_path / "unsafe.tex"
    tex.write_text(r"\input{secret}", encoding="utf-8")
    monkeypatch.setattr(compile_pdf, "_find_engine", lambda engine: "pdflatex")
    monkeypatch.setattr(compile_pdf.subprocess, "run", lambda *a, **k: pytest.fail("unsafe TeX reached subprocess"))
    assert compile_pdf.compile_tex_to_pdf(str(tex)) is None


def test_compilation_disables_shell_and_sets_read_write_policy(tmp_path, monkeypatch):
    tex = tmp_path / "exam.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    monkeypatch.setattr(compile_pdf, "_find_engine", lambda engine: "pdflatex")
    def run(command, **kwargs):
        assert "-no-shell-escape" in command
        assert kwargs["env"]["openin_any"] == "p"
        assert kwargs["env"]["openout_any"] == "p"
        assert kwargs["env"]["shell_escape"] == "0"
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= 60
        tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\nsynthetic")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(compile_pdf.subprocess, "run", run)
    assert compile_pdf.compile_tex_to_pdf(str(tex)) == str(tex.with_suffix(".pdf"))


def test_unsupported_engine_and_large_source_never_execute(tmp_path, monkeypatch):
    tex = tmp_path / "exam.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    monkeypatch.setattr(compile_pdf, "_find_engine", lambda engine: "fake")
    monkeypatch.setattr(compile_pdf.subprocess, "run", lambda *a, **k: pytest.fail("unsupported input executed"))
    assert compile_pdf.compile_tex_to_pdf(str(tex), engine="lualatex") is None
    tex.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
    assert compile_pdf.compile_tex_to_pdf(str(tex)) is None


def test_timeout_returns_failure_and_cannot_serve_a_stale_pdf(tmp_path, monkeypatch):
    tex = tmp_path / "exam.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\nstale")
    monkeypatch.setattr(compile_pdf, "_find_engine", lambda engine: "pdflatex")
    def run(*a, **k):
        raise subprocess.TimeoutExpired("pdflatex", 30)
    monkeypatch.setattr(compile_pdf.subprocess, "run", run)
    assert compile_pdf.compile_tex_to_pdf(str(tex)) is None
    assert not tex.with_suffix(".pdf").exists()


def test_failed_first_pass_is_failure_even_if_second_pass_could_succeed(tmp_path, monkeypatch):
    tex = tmp_path / "exam.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    monkeypatch.setattr(compile_pdf, "_find_engine", lambda engine: "pdflatex")
    def run(*a, **k):
        tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\npartial")
        return SimpleNamespace(returncode=1, stdout="! synthetic failure", stderr="")
    monkeypatch.setattr(compile_pdf.subprocess, "run", run)
    assert compile_pdf.compile_tex_to_pdf(str(tex)) is None
    assert not tex.with_suffix(".pdf").exists()


def _responses():
    from src.utils import pdf_response
    return pdf_response


def test_failed_temp_compile_removes_workdir(monkeypatch):
    responses = _responses()
    created = []
    def fail(path, **kwargs):
        created.append(Path(path).parent)
        return None
    monkeypatch.setattr(responses, "compile_tex_to_pdf", fail)
    assert responses.compile_temp_pdf(GOOD_TEX, "../../exam") is None
    assert created and not created[0].exists()


def test_response_cleans_temp_after_background_task_and_sanitizes_filename(monkeypatch):
    responses = _responses()
    def compile_ok(path, **kwargs):
        pdf = Path(path).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\nsynthetic")
        return str(pdf)
    monkeypatch.setattr(responses, "compile_tex_to_pdf", compile_ok)
    response = responses.compile_pdf_response(GOOD_TEX, "../../exam")
    workdir = Path(response.path).parent
    assert workdir.exists()
    assert response.filename == "exam.pdf"
    assert response.background is not None
    response.background.func(*response.background.args, **response.background.kwargs)
    assert not workdir.exists()


def test_cleanup_never_deletes_unowned_directory(tmp_path):
    responses = _responses()
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4\nowned elsewhere")
    responses.cleanup_temp_pdf(str(pdf))
    assert pdf.exists()


def test_invalid_tex_and_missing_compiler_produce_clean_http_errors(monkeypatch):
    responses = _responses()
    with pytest.raises(HTTPException) as invalid:
        responses.compile_pdf_response(r"\input{secret}", "exam")
    assert invalid.value.status_code == 422
    monkeypatch.setattr(responses, "compile_tex_to_pdf", lambda *a, **k: None)
    with pytest.raises(HTTPException) as unavailable:
        responses.compile_pdf_response(GOOD_TEX, "exam")
    assert unavailable.value.status_code == 503


def test_check_compiles_always_cleans_successful_temp(monkeypatch):
    responses = _responses()
    created = []
    def compile_ok(path, **kwargs):
        pdf = Path(path).with_suffix(".pdf")
        created.append(pdf.parent)
        pdf.write_bytes(b"%PDF-1.4\nsynthetic")
        return str(pdf)
    monkeypatch.setattr(responses, "compile_tex_to_pdf", compile_ok)
    assert responses.check_tex_compiles(GOOD_TEX, "exam") is True
    assert not created[0].exists()


def test_interrupted_response_always_releases_owned_directory(monkeypatch):
    responses = _responses()
    def compile_ok(path, **kwargs):
        pdf = Path(path).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\nsynthetic")
        return str(pdf)
    monkeypatch.setattr(responses, "compile_tex_to_pdf", compile_ok)
    response = responses.compile_pdf_response(GOOD_TEX, "exam")
    directory = Path(response.path).parent
    async def interrupted_stream(*args, **kwargs):
        raise RuntimeError("client disconnected")
    monkeypatch.setattr(responses.FileResponse, "__call__", interrupted_stream)
    with pytest.raises(RuntimeError):
        # This coroutine raises before yielding; no event loop or sockets needed.
        response({}, None, None).send(None)
    assert not directory.exists()
