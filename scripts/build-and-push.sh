#!/usr/bin/env bash
#
# Build and push the mteam-cli image to Docker Hub.
#
# Versioning is automated: the single source of truth is the `version` field
# in pyproject.toml. This script derives the image tags from it, so to cut a
# new release you only bump the version there and re-run this script.
#
#   knowswlf/mteam-cli:<version>   # immutable, e.g. 0.1.0
#   knowswlf/mteam-cli:latest      # moving pointer to the newest build
#
# Usage:
#   ./scripts/build-and-push.sh                # build + push <version> and latest
#   ./scripts/build-and-push.sh --version-only # print the derived version and exit
#   ./scripts/build-and-push.sh --no-push      # build locally, don't push
#   VERSION=0.2.0 ./scripts/build-and-push.sh  # override the version tag
#
# Requires: docker, and `docker login` to an account that can push to IMAGE_REPO.

set -euo pipefail

IMAGE_REPO="${IMAGE_REPO:-knowswlf/mteam-cli}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

derive_version() {
  if [[ -n "${VERSION:-}" ]]; then
    printf '%s' "${VERSION}"
    return
  fi
  local v
  v="$(grep -m1 -E '^\s*version\s*=' "${ROOT_DIR}/pyproject.toml" \
        | sed -E 's/.*"([^"]+)".*/\1/')"
  if [[ -z "${v}" ]]; then
    echo "ERROR: could not read version from pyproject.toml" >&2
    exit 1
  fi
  printf '%s' "${v}"
}

VERSION="$(derive_version)"

if [[ "${1:-}" == "--version-only" ]]; then
  printf '%s\n' "${VERSION}"
  exit 0
fi

PUSH=1
[[ "${1:-}" == "--no-push" ]] && PUSH=0

VERSION_TAG="${IMAGE_REPO}:${VERSION}"
LATEST_TAG="${IMAGE_REPO}:latest"

echo "==> Building ${VERSION_TAG} (+ latest)"
docker build \
  --label "org.opencontainers.image.version=${VERSION}" \
  --label "org.opencontainers.image.source=https://hub.docker.com/r/${IMAGE_REPO}" \
  -t "${VERSION_TAG}" \
  -t "${LATEST_TAG}" \
  "${ROOT_DIR}"

if [[ "${PUSH}" -eq 1 ]]; then
  echo "==> Pushing ${VERSION_TAG}"
  docker push "${VERSION_TAG}"
  echo "==> Pushing ${LATEST_TAG}"
  docker push "${LATEST_TAG}"
  echo "==> Done. Published ${VERSION_TAG} and ${LATEST_TAG}"
else
  echo "==> Built locally (push skipped). Tags: ${VERSION_TAG}, ${LATEST_TAG}"
fi
