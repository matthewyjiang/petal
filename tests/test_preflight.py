from __future__ import annotations

import sys

import pytest

from petal import preflight


def _which_missing(*missing: str):
    """Return a shutil.which replacement that returns None for the listed tools."""
    def which(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None if name in missing else f"/usr/bin/{name}"
    return which


def test_all_tools_present(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name, *a, **kw: f"/usr/bin/{name}")
    report = preflight.check()
    assert report.ok
    assert not report.errors
    assert not report.warnings


def test_missing_uv_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", _which_missing("uv"))
    report = preflight.check()
    assert not report.ok
    assert any("uv" in e for e in report.errors)


def test_missing_rosdep_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", _which_missing("rosdep"))
    report = preflight.check()
    assert not report.ok
    assert any("rosdep" in e for e in report.errors)


def test_missing_apt_tool_is_warning_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", _which_missing("apt-cache"))
    monkeypatch.setattr(sys, "platform", "linux")
    report = preflight.check()
    assert any("apt-cache" in w for w in report.warnings)
    # Missing apt-cache alone is not a hard error
    # (uv and rosdep are present in this test)
    assert report.ok


def test_missing_apt_tool_not_warned_on_non_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", _which_missing("apt-cache", "apt-get", "dpkg-query"))
    monkeypatch.setattr(sys, "platform", "darwin")
    report = preflight.check()
    assert not any("apt" in w for w in report.warnings)


def test_assert_ok_raises_on_errors(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", _which_missing("uv", "rosdep"))
    report = preflight.check()
    with pytest.raises(SystemExit) as exc:
        preflight.assert_ok(report)
    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert "uv" in stderr
    assert "rosdep" in stderr


def test_assert_ok_passes_with_only_warnings(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", _which_missing("apt-cache"))
    monkeypatch.setattr(sys, "platform", "linux")
    report = preflight.check()
    preflight.assert_ok(report)  # should not raise
    stderr = capsys.readouterr().err
    assert "warning" in stderr
