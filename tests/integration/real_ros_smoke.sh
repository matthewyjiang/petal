#!/usr/bin/env bash
set -euo pipefail

if [[ "${PETAL_REAL_ROS_SMOKE:-}" != "1" ]]; then
  echo "Skipping real ROS smoke; set PETAL_REAL_ROS_SMOKE=1 to run." >&2
  exit 0
fi

for tool in rosdep apt-get uv colcon; do
  command -v "$tool" >/dev/null || {
    echo "Missing required tool for real ROS smoke: $tool" >&2
    exit 1
  }
done

: "${ROS_DISTRO:?ROS_DISTRO must be set by sourcing /opt/ros/<distro>/setup.bash}"
ros_setup="/opt/ros/${ROS_DISTRO}/setup.bash"
[[ -f "$ros_setup" ]] || {
  echo "Missing ROS setup file: $ros_setup" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$ros_setup"

workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT
cd "$workspace"

mkdir -p src/smoke_pkg
cat > src/smoke_pkg/package.xml <<'XML'
<?xml version="1.0"?>
<package format="3">
  <name>smoke_pkg</name>
  <version>0.0.0</version>
  <description>Petal real ROS smoke package</description>
  <maintainer email="smoke@example.com">Petal Smoke</maintainer>
  <license>MIT</license>
  <exec_depend>rclpy</exec_depend>
</package>
XML

petal init --workspace "$workspace"
test -f petal.toml
test -x .petal/activate
grep -q 'include-system-site-packages = true' .petal/venv/pyvenv.cfg

petal sync --workspace "$workspace" --yes
petal status --workspace "$workspace"
colcon deps status --workspace "$workspace"

bash -c 'source <(petal activate --workspace "$1" --shell bash); python - <<"PY"
import os
import rclpy
assert os.environ.get("VIRTUAL_ENV", "").endswith("/.petal/venv")
PY
' _ "$workspace"

echo "real ROS smoke passed for ROS_DISTRO=${ROS_DISTRO}"