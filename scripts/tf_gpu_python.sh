#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_VENV="${ROOT_DIR}/.venv-tf"
TF_PYTHON="${TF_VENV}/bin/python"

if [[ ! -x "${TF_PYTHON}" ]]; then
  echo "Missing TensorFlow GPU venv: ${TF_PYTHON}" >&2
  echo "Create it with: python3 -m venv .venv-tf" >&2
  exit 1
fi

SITE_PACKAGES="$("${TF_PYTHON}" -c 'import site; print(site.getsitepackages()[0])')"
NVIDIA_DIR="${SITE_PACKAGES}/nvidia"

TF_LIBS=""
if [[ -d "${NVIDIA_DIR}" ]]; then
  TF_LIBS="$(find "${NVIDIA_DIR}" -maxdepth 3 -type d -name lib | paste -sd: -)"
fi

export LD_LIBRARY_PATH="${TF_LIBS:+${TF_LIBS}:}/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
exec "${TF_PYTHON}" "$@"
