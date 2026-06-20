from __future__ import annotations

import subprocess
from pathlib import Path

from petal.installer import write_lock
from petal.models import Dep, ResolvedDep, Source
from petal.status import check_status, print_report


def completed(
    cmd: list[str], stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def make_workspace(tmp_path: Path) -> Path:
    manifest = tmp_path / "petal.toml"
    manifest.write_text('[workspace]\nros_distro = "humble"\n', encoding="utf-8")
    resolved = [
        ResolvedDep(
            Dep("numpy"), Source.APT, resolved_version="1.24", apt_pkg="python3-numpy"
        ),
        ResolvedDep(Dep("rich"), Source.PIP, resolved_version="13.7.0"),
        ResolvedDep(Dep("rclpy"), Source.DISTRO),
    ]
    write_lock(tmp_path / "petal.lock", manifest, resolved)
    return tmp_path


def test_status_reports_in_sync(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, "1.24")
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"rich","version":"13.7.0"}]')
        if cmd[-2:] == ["-c", "import rclpy"]:
            return completed(cmd)
        return completed(cmd, returncode=1)

    report = check_status(ws, ws / ".petal" / "venv", runner)
    assert report.ok
    assert report.in_sync == ["numpy", "rich", "rclpy"]


def test_status_uses_canonical_pip_identity_for_underscore_alias(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text('[workspace]\nros_distro = "humble"\n', encoding="utf-8")
    write_lock(
        tmp_path / "petal.lock",
        manifest,
        [ResolvedDep(Dep("foo_bar"), Source.PIP, resolved_version="1.0")],
    )

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"foo-bar","version":"1.0"}]')
        return completed(cmd, returncode=1)

    report = check_status(tmp_path, tmp_path / ".petal" / "venv", runner)

    assert report.ok
    assert report.in_sync == ["foo_bar"]


def test_status_treats_malformed_pip_json_as_missing(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text('[workspace]\nros_distro = "humble"\n', encoding="utf-8")
    write_lock(
        tmp_path / "petal.lock",
        manifest,
        [ResolvedDep(Dep("rich"), Source.PIP, resolved_version="13.7.0")],
    )

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, "not json")
        return completed(cmd, returncode=1)

    report = check_status(tmp_path, tmp_path / ".petal" / "venv", runner)

    assert not report.ok
    assert report.missing == ["rich"]


def test_status_reports_drift_missing_and_manifest_change(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (ws / "petal.toml").write_text(
        '[workspace]\nros_distro = "jazzy"\n', encoding="utf-8"
    )

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, "1.25")
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, "[]")
        if cmd[-2:] == ["-c", "import rclpy"]:
            return completed(cmd, returncode=1)
        return completed(cmd, returncode=1)

    report = check_status(ws, ws / ".petal" / "venv", runner)
    assert not report.ok
    assert report.manifest_changed
    assert report.drifted == ["numpy (1.25 != 1.24)"]
    assert report.missing == ["rich", "rclpy"]


def test_status_accepts_importable_apt_python_dep_when_dpkg_missing(
    tmp_path: Path,
) -> None:
    ws = make_workspace(tmp_path)

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, returncode=1)
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"rich","version":"13.7.0"}]')
        if cmd[-2:] == ["-c", "import numpy"]:
            return completed(cmd)
        if cmd[-2:] == ["-c", "import rclpy"]:
            return completed(cmd)
        return completed(cmd, returncode=1)

    report = check_status(ws, ws / ".petal" / "venv", runner)

    assert report.ok
    assert report.in_sync == ["numpy", "rich", "rclpy"]
    assert report.missing == []


def test_status_uses_known_import_name_for_distro_dep(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text('[workspace]\nros_distro = "humble"\n', encoding="utf-8")
    write_lock(
        tmp_path / "petal.lock",
        manifest,
        [ResolvedDep(Dep("pyyaml"), Source.DISTRO)],
    )

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[-2:] == ["-c", "import yaml"]:
            return completed(cmd)
        return completed(cmd, returncode=1)

    report = check_status(tmp_path, tmp_path / ".petal" / "venv", runner)

    assert report.ok
    assert report.in_sync == ["pyyaml"]


def test_print_report_ok_is_concise(capsys) -> None:  # type: ignore[no-untyped-def]
    ws_report = check_status(
        Path("/does/not/exist"), Path("/venv"), lambda cmd, **kwargs: completed(cmd)
    )
    ws_report.missing.clear()
    ws_report.in_sync.extend(["numpy", "rich"])

    print_report(ws_report)

    assert capsys.readouterr().out == "2 synced\n"


def test_print_report_issues_are_bulleted(capsys) -> None:  # type: ignore[no-untyped-def]
    ws_report = check_status(
        Path("/does/not/exist"), Path("/venv"), lambda cmd, **kwargs: completed(cmd)
    )
    print_report(ws_report)
    out = capsys.readouterr().out
    assert "0 synced  ·  1 missing" in out
    assert "  missing:\n    petal.lock" in out
