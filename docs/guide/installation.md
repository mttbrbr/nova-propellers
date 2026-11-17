# Installation

## In brief

You can run NOVA in three ways: with **Docker** (the quickest, nothing to compile), as a **Linux
desktop application** (Arch or Debian/Ubuntu packages), or **from source** if you develop it. Your
data always stays on your own computer.

```{warning}
NOVA is **alpha** software, meant for learning, experimentation and research. It is not a certified
engineering tool: the built-in polars are synthetic data, and every result must be independently
validated before anything is manufactured or flown.
```

## In detail

### With Docker

You only need Docker Engine (or Docker Desktop) and Docker Compose v2. The pre-built images are
downloaded from the GitHub container registry, so nothing is compiled on your machine:

```bash
git clone https://github.com/mttbrbr/nova-propellers.git
cd nova-propellers
docker compose pull
docker compose up --detach --no-build
```

Once both containers are healthy, open the interface at <http://localhost:5173>. The interactive API
documentation is at <http://localhost:8000/docs> and the health check at
<http://localhost:8000/api/health>.

Everyday commands:

```bash
docker compose ps          # container status
docker compose logs -f     # live log
docker compose down        # stop
```

To update to the latest release run `git pull`, then `docker compose pull` and
`docker compose up --detach --no-build` again. To pin a release, copy `.env.example` to `.env` and
set `NOVA_IMAGE_TAG`; if port 5173 or 8000 is taken, change `NOVA_FRONTEND_PORT` or
`NOVA_BACKEND_PORT` in the same file.

```{note}
Projects and imported airfoils live in the `nova_backend_data` Docker volume: a normal restart or
`docker compose down` keeps them. `docker compose down --volumes` deletes them.
```

### Linux desktop application

The desktop application is a Tauri 2 window that starts the calculation engine by itself and opens
the interface: no Docker and no Python environment to configure. The main development platform is
Arch Linux; Arch and Debian/Ubuntu 24.04 packages can be built from the repository.

For Arch, from a checkout of the repository:

```bash
./tools/package_arch.sh
sudo pacman -U packaging/arch/nova-propellers-*.pkg.tar.zst
```

For Debian packages, build on the oldest supported distribution (Ubuntu 24.04): a binary built on
Arch can require a newer `glibc`. The exact commands are in the repository's `DESKTOP_LINUX.md`.

### From source (development)

On Arch Linux:

```bash
sudo pacman -S --needed base-devel git nodejs npm rust uv webkit2gtk-4.1
uv python install 3.12
npm ci --prefix frontend
npm --prefix frontend run desktop:live
```

`desktop:live` runs the engine straight from the Python sources with automatic reload, then starts
Tauri with hot reload of the interface. The first Rust build takes a while.

### Common problems

**[TO COMPLETE]** Collect the most common start-up errors here (busy ports, engine not responding,
and so on) as they emerge from real use.
