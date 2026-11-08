from __future__ import annotations

from pathlib import Path

from petal.config import add_manifest_dep, find_workspace_root, remove_manifest_dep
from petal.models import Source


def test_add_manifest_dep_preserves_overrides(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        "[workspace]\n"
        'ros_distro = "humble"\n'
        'python_version = "3.10"\n'
        "\n"
        "[deps]\n"
        'numpy = ">=1.24"\n'
        "\n"
        "[overrides]\n"
        'ml_collections = { pip = "ml-collections" }\n',
        encoding="utf-8",
    )

    add_manifest_dep(manifest, "rich", version_spec=">=13", source_hint=Source.PIP)

    text = manifest.read_text(encoding="utf-8")
    assert 'rich = { pip = ">=13" }' in text
    assert '[overrides]\nml_collections = { pip = "ml-collections" }' in text


def test_add_manifest_dep_updates_existing_canonical_key(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text('[deps]\nml_collections = "*"\n', encoding="utf-8")

    add_manifest_dep(manifest, "ml-collections", version_spec=">=0.1")

    text = manifest.read_text(encoding="utf-8")
    assert 'ml-collections = ">=0.1"' not in text
    assert 'ml_collections = ">=0.1"' in text
    assert text.count("ml_collections") == 1


def test_add_manifest_dep_renders_apt_default(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")

    add_manifest_dep(manifest, "numpy", source_hint=Source.APT)

    assert 'numpy = { apt = "python3-numpy" }' in manifest.read_text(encoding="utf-8")


def test_remove_manifest_dep_uses_canonical_key(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[deps]\nml_collections = "*"\nrich = ">=13"\n', encoding="utf-8"
    )

    assert remove_manifest_dep(manifest, "ml-collections") is True
    text = manifest.read_text(encoding="utf-8")
    assert "ml_collections" not in text
    assert 'rich = ">=13"' in text


def test_workspace_root_skips_packages_with_their_own_src(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "pkg_cpp"
    (pkg / "src").mkdir(parents=True)
    (pkg / "package.xml").write_text("<package/>", encoding="utf-8")

    assert find_workspace_root(pkg) == tmp_path
    assert find_workspace_root(pkg / "src") == tmp_path


def test_workspace_root_prefers_petal_toml_over_nearer_src(tmp_path: Path) -> None:
    (tmp_path / "petal.toml").write_text("[deps]\n", encoding="utf-8")
    nested = tmp_path / "src" / "vendor" / "some_ws"
    (nested / "src").mkdir(parents=True)

    assert find_workspace_root(nested) == tmp_path


def test_workspace_root_prefers_petal_toml_over_a_src_layout_subtree(
    tmp_path: Path,
) -> None:
    (tmp_path / "petal.toml").write_text("[deps]\n", encoding="utf-8")
    webui = tmp_path / "tools" / "webui"
    (webui / "src").mkdir(parents=True)

    assert find_workspace_root(webui) == tmp_path
