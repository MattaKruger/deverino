# Podman Integration Plan

**Date:** 2026-06-13
**Scope:** Adopt the harness to use Podman on Linux (Fedora 44) while preserving Docker on macOS.

## Executive Summary

The harness **code is already fully Podman-compatible.** All three container tools
(`container_spawn.py`, `container_exec.py`, `container_destroy.py`) have
`BACKENDS = ("podman", "docker")` with podman-first auto-detection via
`shutil.which()`. The `docker-compose.yml` uses standard Compose spec syntax
that both `podman-compose` and `docker compose` support.

This is purely a **documentation + dev tooling** change across 4 files.

---

## Fedora 44 Prerequisite

```bash
sudo dnf install -y podman podman-compose
```

Enable and start the podman socket (rootless):

```bash
systemctl --user enable --now podman.socket
```

---

## SELinux Volume Persistence (Critical for Fedora)

**The problem:** Volumes disappearing after logout/restart on Fedora is a known
Podman + SELinux interaction. The root cause is typically one of:

1. **SELinux label mismatch on bind mounts.** Podman runs containers with the
   `container_t` SELinux type. If a host directory doesn't have the
   `container_file_t` label, the container can't read/write it — the data
   *appears* to be gone but is actually just inaccessible.

2. **Runtime directory cleanup.** Rootless Podman stores temp data in
   `$XDG_RUNTIME_DIR` (`/run/user/$UID`), which is cleaned on logout. Persistent
   named volumes live in `~/.local/share/containers/storage/volumes/` and
   survive reboots — **but only if SELinux allows access.**

### Fix: SELinux volume labels in docker-compose.yml

Podman's `:z` and `:Z` volume flags relabel files for container access:

| Flag | Behaviour | Use when |
|---|---|---|
| `:z` | Shared label — multiple containers can read/write | Volumes shared between services |
| `:Z` | Private label — only this container can access | Single-tenant database volumes |

**The current `docker-compose.yml` uses no SELinux labels.** On Docker (macOS)
this is fine — there's no SELinux. On Fedora with SELinux enforcing, the bind
mount `./vespa/document_retrieval:/vespa-app:ro` will fail because the host
directory lacks `container_file_t`.

**Recommended additions to docker-compose.yml:**

```yaml
# Postgres volumes (private, single-container): append :Z
volumes:
  - pgdata:/var/lib/postgresql:Z

# Vespa data volume (private): append :Z
volumes:
  - vespadata:/opt/vespa/var:Z

# Vespa app bind mount (shared, read-only): append :z
volumes:
  - ./vespa/document_retrieval:/vespa-app:ro,z
```

**Alternative (if `:z`/`:Z` relabeling is too slow on large volumes):**
Set the SELinux context manually once on the host:

```bash
sudo semanage fcontext -a -t container_file_t "/path/to/vespa/document_retrieval(/.*)?"
sudo restorecon -Rv /path/to/vespa/document_retrieval
```

Or disable SELinux separation for the container entirely:

```yaml
security_opt:
  - label=disable
```

### Verifying SELinux is the culprit

```bash
# Check if SELinux is enforcing
getenforce

# Look for AVC denials in the audit log
sudo ausearch -m avc -ts recent | grep -i container

# Check SELinux context of a host directory
ls -Z vespa/document_retrieval/
```

---

## Changes (5 files)

### 1. `Justfile` — Auto-detect compose backend + add convenience recipes

Add an auto-detection variable at the top:

```just
# Auto-detect container compose backend (podman on Linux, docker on macOS)
compose := `command -v podman >/dev/null 2>&1 && echo "podman compose" || echo "docker compose"`
```

Update all hardcoded `docker compose` references:

| Recipe | Current | New |
|--------|---------|-----|
| `test-db-up` | `docker compose up -d postgres_test` | `{{compose}} up -d postgres_test` |
| `test-db-down` | `docker compose stop postgres_test` | `{{compose}} stop postgres_test` |

Add new convenience recipes:

```just
# Start backing services (Postgres + Vespa)
services-up:
    {{compose}} up -d postgres vespa

# Stop backing services without deleting data
services-down:
    {{compose}} stop

# Deploy Vespa application package
vespa-deploy:
    {{compose}} exec vespa vespa deploy /vespa-app

# Start just the main database
db-up:
    {{compose}} up -d postgres

# Stop the main database
db-down:
    {{compose}} stop postgres
```

### 2. `docker-compose.yml` — Add SELinux volume labels

Add `:Z` (private) and `:z` (shared) labels to volumes so Podman can access
them under SELinux enforcing. These labels are **no-ops on Docker/macOS** —
they're silently ignored when SELinux isn't present.

```yaml
volumes:
  # Postgres: private label
  - pgdata:/var/lib/postgresql:Z

  # Test Postgres: private label  
  - pgdata_test:/var/lib/postgresql:Z

  # Vespa data: private label
  - vespadata:/opt/vespa/var:Z

  # Vespa app bind mount: shared, read-only
  - ./vespa/document_retrieval:/vespa-app:ro,z
```

### 3. `README.md` — Update Quickstart

Replace raw `docker compose` commands with Justfile recipes:

```markdown
## Quickstart

Start the local backing services (Postgres + Vespa):

```bash
just services-up
just vespa-deploy
```

Stop the services without deleting indexed state:

```bash
just services-down
```
```

Add a container runtime note:

```markdown
### Container runtime

The harness auto-detects your container backend — **Podman** on Linux,
**Docker** on macOS. Install either:

- **Fedora:** `sudo dnf install podman podman-compose`
- **macOS:** `brew install --cask docker` (or Podman Desktop)
```

Update volume wording: "Docker volumes" → "named volumes".

### 4. `CLAUDE.md` — Update descriptions (2 spots)

- Line 65: `Docker container lifecycle` → `Docker/Podman container lifecycle`
- Line 111: `docker-compose.yml runs Vespa locally` → `compose file runs Vespa locally`

### 5. `Dockerfile` — Update build comment

```dockerfile
#   docker build -t deverino-python:latest .
#   podman build -t deverino-python:latest .
```

---

## What does NOT need changing

| Component | Why unchanged |
|---|---|
| `harness_poc/system_tools/container_spawn.py` | Already has `BACKENDS = ("podman", "docker")`, tries podman first |
| `harness_poc/system_tools/container_exec.py` | Same pattern, supports `podman`/`docker`/`auto` |
| `harness_poc/system_tools/container_destroy.py` | Same pattern |
| `docker-compose.yml` | **Needs SELinux `:z`/`:Z` labels added** (no-ops on Docker/macOS) |
| `harness.yaml` | Database/vespa URLs point to `localhost` — works regardless of backend |
| `pyproject.toml` | No Docker-specific dependencies |
| `tests/` | No tests hardcode `docker`; integration tests use `TEST_DATABASE_URL` env var |

---

## Verification Plan

After applying changes on the Fedora 44 machine:

```bash
# 1. Verify podman is functional
podman run --rm hello-world

# 2. Verify podman-compose works
just services-up
just vespa-deploy

# 3. Run the test suite
just test

# 4. Verify container spawn in REPL
uv run harness-poc
# > /container_spawn  (should use podman)
```
