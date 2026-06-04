from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field


@dataclass
class PreflightReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check() -> PreflightReport:
    """Check that required external tools are available."""
    report = PreflightReport()

    # uv — required for pip resolution and install
    if not shutil.which("uv"):
        report.errors.append(
            "uv is not installed or not on PATH.\n"
            "  Install: curl -Ls https://astral.sh/uv/install.sh | sh\n"
            "  Docs:    https://docs.astral.sh/uv/"
        )

    # rosdep — required for ROS dependency resolution
    if not shutil.which("rosdep"):
        report.errors.append(
            "rosdep is not installed or not on PATH.\n"
            "  Install: sudo apt install python3-rosdep\n"
            "  Then:    sudo rosdep init && rosdep update"
        )

    # apt tools — only expected on Debian/Ubuntu
    if sys.platform == "linux":
        for tool in ("apt-cache", "apt-get", "dpkg-query"):
            if not shutil.which(tool):
                report.warnings.append(
                    f"{tool} not found. apt-based dependency resolution will be skipped."
                )

    return report


def assert_ok(report: PreflightReport) -> None:
    """Print warnings, then raise SystemExit if there are errors."""
    for warning in report.warnings:
        print(f"petal: warning: {warning}", file=__import__("sys").stderr)
    if not report.ok:
        for error in report.errors:
            print(f"petal: error: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
