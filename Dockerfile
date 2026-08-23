# syntax=docker/dockerfile:1.7
#
# Reproducible governance-harness image. The base tag and digest are both
# retained: the tag documents the Python ABI while the digest pins its bytes.
FROM python:3.11.11-slim-bookworm@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5

ARG TARGETARCH
ARG UV_VERSION=0.6.3
ARG GITLEAKS_VERSION=8.28.0
ARG OSV_SCANNER_VERSION=2.2.4

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/hexvision/venv \
    PATH=/opt/hexvision/venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

WORKDIR /app

# `uv` is installed at an exact version, then is the only dependency installer
# used for the application. The lockfile is copied before source for cacheable,
# lockfile-driven dependency resolution.
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# Download vendor release binaries rather than building from Go (which is not
# present in this image). Verify both the downloaded archive/direct binary and
# the executable bytes that will actually be placed on PATH.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) \
        gitleaks_url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"; \
        gitleaks_release_sha256="a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb"; \
        gitleaks_artifact_sha256="5fd1b3b0073269484d40078662e921d07427340ab9e6ed526ccd215a565b3298"; \
        osv_url="https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64"; \
        osv_sha256="7702cd1e5d9f5059dd9570f4ad967f27d3c5f5391b371ec937b384c238177f55" \
        ;; \
      arm64) \
        gitleaks_url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_arm64.tar.gz"; \
        gitleaks_release_sha256="eff65261156100e5d94a6b3dec313d532fddfe19ae1590bf7a2b4f2699128356"; \
        gitleaks_artifact_sha256="3770c7ebeb625e3e96c183525ca18285a01aedef2d75a2c41ceb3e141af2e8b7"; \
        osv_url="https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_arm64"; \
        osv_sha256="94d1c520b30a7e28b0189b2a1dd24c7b08f41887186e8ae3f811067ec9ed7043" \
        ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}; expected amd64 or arm64" >&2; exit 64 ;; \
    esac; \
    workdir="$(mktemp -d)"; \
    trap 'rm -rf "$workdir"' EXIT; \
    curl --fail --location --silent --show-error --output "$workdir/gitleaks.tar.gz" "$gitleaks_url"; \
    echo "$gitleaks_release_sha256  $workdir/gitleaks.tar.gz" | sha256sum --check --status; \
    tar --extract --gzip --file "$workdir/gitleaks.tar.gz" --directory "$workdir" gitleaks; \
    install --mode 0755 "$workdir/gitleaks" /usr/local/bin/gitleaks; \
    echo "$gitleaks_artifact_sha256  /usr/local/bin/gitleaks" | sha256sum --check --status; \
    curl --fail --location --silent --show-error --output "$workdir/osv-scanner" "$osv_url"; \
    echo "$osv_sha256  $workdir/osv-scanner" | sha256sum --check --status; \
    install --mode 0755 "$workdir/osv-scanner" /usr/local/bin/osv-scanner; \
    echo "$osv_sha256  /usr/local/bin/osv-scanner" | sha256sum --check --status
RUN gitleaks version | grep -F "${GITLEAKS_VERSION}" \
    && osv-scanner --version | grep -F "${OSV_SCANNER_VERSION}"

COPY src ./src
RUN uv sync --locked --no-dev \
    && groupadd --gid 10001 hexvision \
    && useradd --uid 10001 --gid hexvision --create-home --shell /usr/sbin/nologin hexvision \
    && chown -R hexvision:hexvision /app /opt/hexvision

USER hexvision

# Default to the JSON-capable harness command. Callers can append any supported
# `hexvision` subcommand, for example `pack list --json` or `conformance --pack jetson`.
ENTRYPOINT ["uv", "run", "--no-sync", "hexvision"]
CMD ["pack", "list", "--json"]
