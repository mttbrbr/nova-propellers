# Linux desktop development and packaging

Nova's desktop architecture keeps the existing application boundaries:

```text
Tauri 2 lifecycle manager
  -> React/Vite static frontend
    -> HTTP on a dynamic 127.0.0.1 port
      -> bundled FastAPI sidecar
        -> inverse_design, geometry, solvers, persistence and export
```

The Rust layer only owns desktop lifecycle and endpoint discovery. It starts
the PyInstaller sidecar, reads its selected endpoint, polls `/api/health`,
exposes the ready state to the frontend and kills the child when the final
window exits. Scientific code remains ordinary Python and is shared with the
Docker/server workflow.

## Development on Arch Linux

Install the native build prerequisites:

```bash
sudo pacman -S --needed base-devel git nodejs npm rust uv webkit2gtk-4.1
```

Prepare the locked frontend dependencies, Python 3.12 and sidecar, then start
Tauri:

```bash
uv python install 3.12
npm ci --prefix frontend
./tools/build_desktop_backend.sh
npm --prefix frontend run desktop:dev
```

`desktop:dev` starts Vite automatically. The Tauri window remains hidden until
FastAPI answers its health check. A startup failure or later backend crash is
shown in the window with the sidecar error tail and a retry action.

For backend-only debugging, reuse the environment created by the sidecar build:

```bash
NOVA_LOG_LEVEL=debug backend/.venv-desktop/bin/python \
  backend/desktop_launcher.py --port 8000 --data-dir /tmp/nova-desktop-debug
```

The process prints `NOVA_BACKEND_ENDPOINT=...`; inspect its API at
`http://127.0.0.1:8000/docs`. A fixed occupied port fails immediately, while
the default `--port 0` atomically binds a free port. Rust diagnostics are
available with:

```bash
RUST_BACKTRACE=1 npm --prefix frontend run desktop:dev
```

The browser/Docker development path is unchanged. It uses `/api` through the
Vite proxy; `VITE_API_BASE_URL` can point the same frontend at another FastAPI
endpoint when needed.

## Release build

Build the sidecar first, then the Tauri application and configured `.deb`:

```bash
./tools/build_desktop_backend.sh
npm ci --prefix frontend
npm --prefix frontend run desktop:build
```

The native Arch executable is written to `src-tauri/target/release/`. Debian
artifacts use the isolated `src-tauri/target/debian/release/bundle/deb/`
directory so Cargo can never reuse Arch objects. PyInstaller is intentionally used in
one-file mode: its tested NumPy, SciPy and Trimesh wheels need no manually
installed Python runtime. Build on the oldest supported distribution, Ubuntu
24.04, when producing a portable Debian artifact; an Arch-built binary can
require a newer glibc.

## Arch package

From an unreleased checkout, the helper creates a source archive from the
current commit and runs a clean `PKGBUILD` build:

```bash
./tools/package_arch.sh
```

The PKGBUILD deliberately uses Arch's native `/usr/bin/gcc` and an isolated
Cargo home. This prevents a user-level Cargo configuration for a Debian
cross-compiler (such as `x86_64-linux-gnu-gcc`) from affecting the package.

The result is `packaging/arch/nova-propellers-*.pkg.tar.zst`. Install it with:

```bash
sudo pacman -U packaging/arch/nova-propellers-*.pkg.tar.zst
```

For a published/tagged source, the standard Arch/AUR-compatible workflow is:

```bash
cd packaging/arch
makepkg
makepkg -si
```

Build dependencies are `base-devel`, `nodejs`, `npm`, `rust` and `uv`.
Runtime dependencies are `gtk3` and `webkit2gtk-4.1`; Python, NumPy and SciPy
are inside `/usr/bin/nova-backend`. Before future AUR publication, replace the
development `SKIP` source checksum with the checksum of the published tag and
regenerate `.SRCINFO`.

## Ubuntu 24.04 / Debian package

Install the Ubuntu 24.04 build prerequisites (Rust and Node 22 may also be
provided by the standard rustup/setup-node workflows):

```bash
sudo apt update
sudo apt install build-essential curl file libayatana-appindicator3-dev \
  librsvg2-dev libssl-dev libwebkit2gtk-4.1-dev libxdo-dev python3.12 \
  libpython3.12 python3.12-venv wget
```

With Node.js 22, npm and the stable Rust toolchain available, build the package:

```bash
./tools/package_deb.sh
```

Install the resulting bundle with:

```bash
sudo apt install ./src-tauri/target/debian/release/bundle/deb/*.deb
```

The `.deb` declares the WebKitGTK/GTK libraries detected by the Tauri bundler.
It contains both `nova-propellers` and the Ubuntu-built `nova-backend`; no
system Python environment is required at runtime.

The optional reproducible validation container can be prepared with:

```bash
docker build -t nova-tauri-deb-builder \
  -f packaging/deb/Containerfile packaging/deb
docker run --rm -v "$PWD:/workspace" nova-tauri-deb-builder \
  ./tools/package_deb.sh
```

## Files and runtime data

The installed application never writes into `/usr`. Tauri passes its XDG data
directory to FastAPI, normally:

```text
$XDG_DATA_HOME/io.github.mttbrbr.nova-propellers/
```

or `~/.local/share/io.github.mttbrbr.nova-propellers/` when
`XDG_DATA_HOME` is unset. `nova.db`, saved projects, airfoils and generated STL
records live there. A directly launched backend defaults to
`$XDG_DATA_HOME/nova-propellers/`. PyInstaller extracts its one-file runtime
into the system temporary directory and cleans it on exit. Tauri/WebKit use
the normal XDG cache locations. User-triggered exports remain explicit
downloads rather than writes into the installation directory.

## Distribution differences and troubleshooting

- Arch and Ubuntu use the same frontend, FastAPI application and scientific
  core. Only system-dependency installation and packaging differ.
- Arch names the WebKit package `webkit2gtk-4.1`; Ubuntu provides
  `libwebkit2gtk-4.1-0` at runtime and `libwebkit2gtk-4.1-dev` for builds.
- Build `.deb` artifacts on Ubuntu 24.04 to keep their glibc baseline. Do not
  copy a PyInstaller sidecar built on rolling-release Arch into that package.
- The Python wheels bundle their numerical native libraries. OpenSSL and GTK/
  WebKitGTK remain system libraries and are package dependencies.
- On Wayland, WebKitGTK may still use distribution-specific graphics drivers;
  retry under an X11 session when diagnosing driver-only rendering failures.

## Smoke and regression checks

```bash
python tools/smoke_desktop_backend.py \
  src-tauri/binaries/nova-backend-x86_64-unknown-linux-gnu
cargo test --manifest-path src-tauri/Cargo.toml --locked
npm --prefix frontend run lint
npm --prefix frontend run build
```

With `xorg-server-xvfb`, `xdotool`, `openbox` and `procps-ng` installed, the packaged
application lifecycle can also be exercised without a physical display:

```bash
./tools/smoke_desktop_lifecycle.sh /usr/bin/nova-propellers
```

`packaging/arch/PKGBUILD` runs both the sidecar smoke test and Rust tests during
`makepkg`. The desktop package workflow repeats Arch and Ubuntu builds in clean
environments. Existing backend, frontend and Docker Compose CI remains active.

## Docker cleanup candidates

Nothing Docker-related is removed by this migration.

- `Dockerfile`, `backend/Dockerfile`, `frontend/Dockerfile`, Compose files and
  Docker startup configuration remain useful for server deployment and the
  browser-based development/test workflow.
- GHCR publishing remains useful for users who prefer containers and for
  future hosted deployments.
- Docker-only reload overrides and image-publishing documentation could become
  optional if desktop distribution fully replaces container development.
- Compose port configuration and published-image quick-start text become
  deletion candidates only after an explicit post-migration decision.
