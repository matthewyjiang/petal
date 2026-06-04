# `petal` — Implementation Specification

A workspace-scoped Python dependency manager for ROS2. Fills the gap between manual `requirements.txt` juggling and full containerization. Apt-first resolution, pip fallback, lock file, colcon integration.

This document is written as a build spec for a coding agent. It is ordered so that each milestone produces a runnable, testable artifact.

---

## 0. Design Constraints (read first)

These are non-negotiable facts about the ROS2 runtime that shape every decision below. Violating them produces a tool that fails at node startup, not at build time, which is the worst failure mode.

1. **ROS2 runs in one shared Python interpreter.** At runtime, `rclpy`, `launch`, `tf2_ros`, etc. are found on `PYTHONPATH` from `/opt/ros/<distro>/lib/python3.X/site-packages`. There is no per-node isolation.
2. **A naive venv breaks `rclpy`.** A standard `python -m venv` excludes system site-packages, so `import rclpy` fails inside it. Any venv this tool creates MUST be made with `--system-site-packages`.
3. **The distro Python version is fixed.** The venv must use the exact interpreter ROS was built against (e.g. Python 3.10 for Humble, 3.12 for Jazzy). Detect it; never assume.
4. **Apt-installed packages must win by default.** If `python3-numpy` is available via apt, prefer it. Pip-installing `numpy` on top into the same effective path risks shadowing a version other ROS packages link against. Pip is the fallback for packages with no apt/rosdep mapping.
5. **Never touch system site-packages.** All pip installs go into the workspace venv, never `sudo pip` and never `--break-system-packages` against the system interpreter.

The tool's value proposition is a **manifest + lock file + clean resolution**, NOT isolation. Be honest about that in the README.

---

## 1. High-Level Architecture

```
petal/
├── pyproject.toml              # packaging; entry point: petal = petal.cli:main
├── petal/
│   ├── __init__.py
│   ├── cli.py                  # argparse/typer dispatch
│   ├── config.py               # locate workspace, load/write manifest + lock
│   ├── models.py               # dataclasses: Dep, ResolvedDep, Manifest, Lock
│   ├── env.py                  # ROS distro + interpreter detection, venv mgmt
│   ├── discover/
│   │   ├── package_xml.py      # parse <*_depend> rosdep keys
│   │   ├── setup_cfg.py        # parse install_requires
│   │   ├── pyproject.py        # parse [project.dependencies]
│   │   └── workspace.py        # walk src/, aggregate per-package -> graph
│   ├── resolve/
│   │   ├── base.py             # Resolver protocol
│   │   ├── distro.py           # is this already provided by /opt/ros/...?
│   │   ├── apt.py              # apt-cache / dpkg query
│   │   ├── rosdep.py           # shell out to rosdep, parse results
│   │   └── pip.py              # uv-backed resolution into the venv
│   ├── planner.py              # graph -> ordered install plan, conflict detection
│   ├── installer.py            # execute plan, write lock
│   ├── status.py               # diff manifest/lock vs actual installed state
│   └── colcon_ext/             # optional colcon verb + event handler
│       └── verb.py
└── tests/
    ├── fixtures/               # sample workspaces
    └── test_*.py
```

**Language:** Python 3.10+ (must run under the system interpreter, not the venv it manages).
**Key external tools shelled out to:** `rosdep`, `apt-cache`/`dpkg-query`, `uv` (preferred) or `pip`.
**Why `uv`:** fast resolver, real lock semantics, `uv pip install --python <venv>/bin/python` targets an explicit interpreter cleanly. Fall back to `pip` if `uv` absent.

---

## 2. Data Models (`models.py`)

```python
from dataclasses import dataclass, field
from enum import Enum

class Source(str, Enum):
    DISTRO = "distro"   # already in /opt/ros/<distro>, do nothing
    APT    = "apt"      # install via apt (system dep)
    ROSDEP = "rosdep"   # resolve via rosdep key
    PIP    = "pip"      # pip/uv into the workspace venv

@dataclass
class Dep:
    name: str                       # canonical name, e.g. "numpy"
    version_spec: str = ""          # PEP 440 spec, e.g. ">=1.24"
    source_hint: Source | None = None   # explicit override from manifest
    origin_packages: list[str] = field(default_factory=list)  # which ros pkgs asked

@dataclass
class ResolvedDep:
    dep: Dep
    chosen_source: Source
    resolved_version: str = ""      # exact pinned version after resolution
    apt_pkg: str = ""               # e.g. "python3-numpy" when source is apt/rosdep
    transitive: bool = False

@dataclass
class Manifest:
    ros_distro: str                 # "humble"
    python_version: str             # "3.10"
    deps: list[Dep]
    # serialized to petal.toml

@dataclass
class Lock:
    manifest_hash: str              # hash of manifest used to produce this lock
    resolved: list[ResolvedDep]
    # serialized to petal.lock (TOML or JSON)
```

---

## 3. Manifest & Lock File Formats

**`petal.toml`** (workspace root, human-edited source of truth):

```toml
[workspace]
ros_distro = "humble"          # auto-filled on init; overridable
python_version = "3.10"        # auto-detected from the distro interpreter

[deps]
# Bare string = version spec, source auto-resolved (apt/rosdep preferred, pip fallback)
numpy = ">=1.24"
scipy = "*"

# Table form for explicit control
torch = { pip = ">=2.1", index = "https://download.pytorch.org/whl/cpu" }
ml-collections = { pip = ">=0.1.1" }
some-system-lib = { apt = "libfoo-dev" }

[overrides]
# Local rosdep-key replacements: declare mappings rosdep's DB doesn't have,
# WITHOUT editing the external rosdistro repo.
ml_collections = { pip = "ml-collections" }   # rosdep key -> pip name
```

**`petal.lock`** (generated, committed for reproducibility):

```toml
manifest_hash = "sha256:..."
generated_at = "2026-06-03T..."
ros_distro = "humble"
python_version = "3.10"

[[resolved]]
name = "numpy"
source = "apt"
apt_pkg = "python3-numpy"
version = "1.24.0-1ubuntu1"

[[resolved]]
name = "torch"
source = "pip"
version = "2.1.2+cpu"
hash = "sha256:..."        # from uv lock, for --frozen verification

[[resolved]]
name = "rclpy"
source = "distro"          # provided by /opt/ros/humble, no action
version = "3.3.7"
```

---

## 4. Environment Detection (`env.py`)

Critical and easy to get wrong. Implement and unit-test this first.

```python
def detect_ros_distro() -> str:
    # 1. $ROS_DISTRO env var if set (most reliable)
    # 2. else glob /opt/ros/* and pick the one whose setup.bash exists
    # 3. error with actionable message if none

def distro_python(distro: str) -> Path:
    # Return the interpreter ROS was built against.
    # glob /opt/ros/<distro>/lib/python3.* -> extract X.Y
    # Resolve to /usr/bin/python3.X (must match exactly).
    # This is the interpreter the venv MUST be created with.

def venv_path(workspace_root: Path) -> Path:
    return workspace_root / ".petal" / "venv"

def ensure_venv(workspace_root: Path, distro: str) -> Path:
    # Create with the distro interpreter AND --system-site-packages:
    #   <distro_python> -m venv --system-site-packages <venv_path>
    # touch <venv_path>/COLCON_IGNORE so colcon never tries to build it.
    # Idempotent: if venv exists and python version matches, no-op.
    # If version mismatch (distro changed), error and suggest `petal clean`.

def distro_provided_modules(distro: str) -> set[str]:
    # List top-level modules already importable from
    #   /opt/ros/<distro>/lib/python3.X/site-packages
    # AND from the system dist-packages.
    # Used by the DISTRO resolver to short-circuit. Cache to disk.
```

**Activation contract for the user:** the venv must be sourced *after* the ROS setup.bash. Generate a helper `source .petal/activate` that does:
```bash
source /opt/ros/<distro>/setup.bash
source .petal/venv/bin/activate
```
Document that order matters (ROS first, venv second) so the venv's `--system-site-packages` view picks up the already-sourced ROS paths.

---

## 5. Discovery (`discover/`)

**`package_xml.py`** — parse rosdep keys:
- XML-parse each `package.xml`. Collect text of `<depend>`, `<exec_depend>`, `<build_depend>`, `<build_export_depend>`, `<test_depend>`.
- Each is a rosdep key (NOT necessarily a pip name). Emit `Dep(name=key, source_hint=ROSDEP)`.

**`setup_cfg.py` / `pyproject.py`** — parse direct Python deps:
- `setup.cfg`: `[options] install_requires`.
- `setup.py`: best-effort — import-free static parse via `ast` for the `install_requires=[...]` literal; if it's dynamic, warn and skip (don't exec arbitrary setup.py).
- `pyproject.py`: `[project] dependencies` and `[project.optional-dependencies]`.
- These give PEP 508 requirement strings -> parse with `packaging.requirements.Requirement` into `Dep(name, version_spec, source_hint=PIP)`.

**`workspace.py`** — aggregate:
- Find workspace root: walk up for a dir containing `src/` (or where `petal.toml` lives).
- Walk `src/**` for packages (dir with `package.xml`). Skip anything containing `COLCON_IGNORE`.
- Build `{dep_name: Dep}` merging `origin_packages` and unioning version specs.
- Apply `[overrides]` from the manifest (rosdep-key -> pip-name remapping) here.
- Output: the merged dependency set + a per-package map (for conflict messages).

---

## 6. Resolution (`resolve/`)

Resolver protocol — each answers "can I provide this dep, and at what version?":

```python
class Resolver(Protocol):
    def can_resolve(self, dep: Dep) -> bool: ...
    def resolve(self, dep: Dep) -> ResolvedDep | None: ...
```

**Resolution order (first hit wins, unless `source_hint` forces one):**

1. **`distro.py`** — if `dep.name` (or its known import name) is in `distro_provided_modules`, return `ResolvedDep(source=DISTRO)`. No install. This is the `rclpy`-shadowing guard.
2. **`rosdep.py`** — `rosdep resolve <key>` (shell out). If it maps to an apt package, return `source=APT` with the `apt_pkg`. If rosdep maps it to a pip rule, treat as a PIP resolution but note rosdep agreed.
3. **`apt.py`** — for a bare Python name, probe `python3-<name>` via `apt-cache policy`. If present, `source=APT`.
4. **`pip.py`** — fallback. Use `uv pip compile` (or `pip install --dry-run`) against the venv interpreter to get an exact version + hash. `source=PIP`.

**Implementation notes:**
- `rosdep resolve` output parsing: it prints `#apt` / `#pip` section headers followed by package names. Parse defensively; versions vary across rosdep releases. Add a unit test with captured fixture output.
- Name canonicalization: rosdep keys, apt names (`python3-foo`), and PyPI names (`foo`, `Foo`, `foo-bar` vs `foo_bar`) all differ. Centralize a `canonical(name)` helper using `packaging.utils.canonicalize_name` for the PyPI side and a small known-map for the `python3-` prefix dance.
- Cache resolver results keyed by `(name, version_spec)` within a single run.

---

## 7. Planning & Conflict Detection (`planner.py`)

```python
def build_plan(resolved: list[ResolvedDep]) -> Plan:
    # 1. Partition by source: distro (noop), apt/rosdep (batch apt install),
    #    pip (single uv resolution pass for the whole pip set together).
    # 2. CONFLICT DETECTION (do this BEFORE any install):
    #    - For each dep name with multiple version specs across packages,
    #      intersect the specifiers (packaging.specifiers.SpecifierSet & merge).
    #      Empty intersection => hard error naming the conflicting packages:
    #        "pkg_a needs numpy>=1.24 but pkg_b needs numpy==1.21"
    #    - Detect a dep resolved BOTH as distro/apt AND requested via pip with an
    #      incompatible version => warn loudly (shadowing risk).
    # 3. Resolve the entire pip set in ONE uv pass so transitive deps are
    #    mutually consistent (not package-by-package).
    # 4. Emit ordered Plan: apt batch first, then pip batch.
```

The single-pass pip resolution is the key correctness win over rosdep's package-by-package model. Feed the whole pip requirement set to `uv pip compile` and let it produce one consistent locked set.

---

## 8. Installer (`installer.py`)

```python
def execute(plan: Plan, venv: Path, *, frozen: bool, dry_run: bool):
    # APT batch:
    #   sudo apt-get install -y <pkgs...>   (only if not already installed;
    #   query dpkg-query -W first). Print the sudo command in dry-run.
    # PIP batch (into the venv, never system):
    #   uv pip install --python <venv>/bin/python -r <compiled-reqs>
    #   (fallback: <venv>/bin/pip install ...)
    #   honor per-dep `index` from manifest.
    # frozen mode: install EXACTLY the versions/hashes from petal.lock;
    #   if a resolved version would differ from lock => error, do not install.
    # After success: write petal.lock with manifest_hash = hash(manifest).
```

Atomicity: resolve and detect conflicts fully before mutating anything. Apt and pip can't be transactionally rolled back cleanly, so the safety comes from full upfront resolution, not rollback.

---

## 9. Status / Drift (`status.py`)

`petal status` — the `git status` analogue:
- Load manifest + lock.
- For each locked dep: check actual installed state.
  - apt: `dpkg-query -W -f='${Version}' <pkg>` vs locked version.
  - pip: query the venv (`uv pip list --python <venv>/bin/python` or import metadata) vs locked.
  - distro: confirm still importable.
- Report three buckets: **in sync**, **drifted** (version differs), **missing** (in lock, not installed). Also flag **manifest changed since lock** (manifest_hash mismatch) -> suggest `petal sync`.

---

## 10. CLI (`cli.py`)

```
petal init        # detect distro+interpreter, write petal.toml, create venv
petal sync        # discover -> resolve -> plan -> install -> write lock
petal sync --frozen   # install exactly from lock; error on any drift (CI)
petal sync --dry-run  # print the plan + commands, install nothing
petal add <name> [--pip|--apt] [spec]   # add to manifest, then sync that dep
petal remove <name>                     # remove from manifest + uninstall from venv
petal status      # drift report
petal clean       # remove .petal/venv (e.g. after distro change)
petal activate    # print path to the source helper, or eval-able shell snippet
```

Use `typer` or stdlib `argparse`. Exit codes: 0 ok, 1 conflict/error, 2 drift (so CI can gate on `status`).

---

## 11. Colcon Integration (`colcon_ext/`) — optional, ship after core works

Two integration modes; implement the verb first (lower risk):

**(a) Verb extension:** register a `colcon deps` verb (entry point group `colcon_core.verb`) that calls `petal sync`. Lets users do `colcon deps sync`.

**(b) Pre-build event handler:** entry point `colcon_core.event_handler` that runs `petal sync --frozen` (or warns on drift) before build. Make it **opt-in** via a flag/env var — silently mutating the environment on every build surprises people. Default to drift-warn, not auto-install.

`pyproject.toml` entry points:
```toml
[project.entry-points."colcon_core.verb"]
deps = "petal.colcon_ext.verb:DepsVerb"
```

---

## 12. Build Order for the Agent (milestones)

Each milestone is independently runnable and testable. Do not proceed until the prior one's tests pass.

1. **M1 — env detection.** `env.py` + tests. `petal init` creates a correct `--system-site-packages` venv with the right interpreter and `COLCON_IGNORE`. Verify `import rclpy` works inside the venv after sourcing ROS.
2. **M2 — discovery.** `discover/` + fixture workspaces (one ament_python pkg with `package.xml` + `setup.cfg`, one with a pip-only dep). Assert the aggregated dep set is correct.
3. **M3 — resolution + distro guard.** Resolvers with captured `rosdep`/`apt-cache` fixtures. Assert `rclpy` resolves to DISTRO (noop), `numpy` to APT, `ml_collections` to PIP.
4. **M4 — planner conflict detection.** Unit-test the spec-intersection logic with conflicting fixtures.
5. **M5 — installer + lock (dry-run first).** `sync --dry-run` prints correct apt + uv commands. Then real install into a throwaway workspace.
6. **M6 — status/drift + frozen.** `status` correctly reports synced/drifted/missing; `sync --frozen` enforces the lock.
7. **M7 — colcon verb.** `colcon deps sync` wraps the core.

---

## 13. Testing Strategy

- **No network in unit tests.** Capture real `rosdep resolve`, `apt-cache policy`, `uv pip compile` outputs as fixtures under `tests/fixtures/cmd_output/` and inject a fake subprocess runner.
- **Fixture workspaces** under `tests/fixtures/ws_*/src/...` with hand-written `package.xml`/`setup.cfg`.
- **One integration test** (marked `@pytest.mark.integration`, opt-in) that runs against a real Humble/Jazzy install in CI (Docker `ros:humble` image) to validate the venv-after-ROS-source contract end to end.
- Property test the spec-intersection in the planner (hypothesis) since that's the subtle correctness core.

---

## 14. Known Edge Cases to Handle Explicitly

- **Distro Python upgraded under you** (e.g. system moved 3.10 -> 3.12): venv interpreter mismatch -> detect in `ensure_venv`, refuse to proceed, suggest `clean`.
- **`uv` not installed:** fall back to `pip`; lose hash-pinning niceties but stay functional. Detect at startup.
- **rosdep key resolves to pip** (rosdep's own pip rules): honor it but record `source=PIP` so the lock is accurate.
- **Editable / VCS deps** (`git+https://...#egg=`): pass through to uv/pip; record the URL in the lock, skip version pinning.
- **Mixed apt+pip for the same package** with incompatible versions: warn, prefer apt, never silently pip-over-apt.
- **No `src/` (installed/overlay-only workspace):** `discover` finds nothing; `sync` is a clean no-op, not an error.
