#!/usr/bin/env bash
# ROS setup scripts read optional unset variables; they are not nounset-safe.
set -eo pipefail

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

# Exercise command/session startup against compiled ROS modules and real RMW
# initialization, not just a fake setup script or an import-only check.
cat > .petal/ros_probe.py <<'PY'
import json
import os
import sys
from pathlib import Path

import rclpy
from std_msgs.msg import String

workspace = Path(os.environ["PETAL_SMOKE_WORKSPACE"])
assert Path(sys.prefix) == workspace / ".petal/venv", sys.prefix
assert Path(os.environ["VIRTUAL_ENV"]) == workspace / ".petal/venv"
assert Path.cwd() == Path(os.environ["PETAL_SMOKE_CWD"]), Path.cwd()

rclpy.init()
try:
    node = rclpy.create_node("petal_environment_smoke")
    try:
        # One local probe message; a depth-one queue is sufficient for it.
        publisher = node.create_publisher(String, "petal_environment_smoke", 1)
        publisher.publish(String(data="petal ROS environment ready"))
    finally:
        node.destroy_node()
finally:
    rclpy.shutdown()

print(json.dumps({
    "result": "ROS node and publisher ready",
    "ros_distro": os.environ["ROS_DISTRO"],
    "python": sys.version.split()[0],
    "executable": sys.executable,
    "rclpy": rclpy.__file__,
    "cwd": str(Path.cwd()),
}))
PY
export PETAL_SMOKE_WORKSPACE="$workspace"
export PETAL_SMOKE_CWD="$workspace"
(
  # Do not let the parent's sourced ROS environment mask broken activation.
  PATH="$(dirname "$(command -v petal)"):/usr/local/bin:/usr/bin:/bin"
  export PATH
  unset AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH LD_LIBRARY_PATH
  unset PYTHONPATH ROS_DISTRO ROS_VERSION ROS_PYTHON_VERSION
  petal run --workspace "$workspace" python "$workspace/.petal/ros_probe.py"
  petal run --workspace "$workspace" ros2 pkg prefix rclpy

  # Workspace lookup must work below the root, without changing the caller's cwd.
  (
    cd src/smoke_pkg
    export PETAL_SMOKE_CWD="$PWD"
    petal run python "$workspace/.petal/ros_probe.py"
  )

  for shell in bash zsh; do
    if command -v "$shell" >/dev/null; then
      printf 'python .petal/ros_probe.py\nexit $?\n' |
        petal shell --workspace "$workspace" --shell "$shell"
    else
      echo "Skipping interactive $shell smoke: shell not installed" >&2
    fi
  done
)

echo "real ROS smoke passed for ROS_DISTRO=${ROS_DISTRO}"
