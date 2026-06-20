#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="agent-session-trajectory"
SKILL_SRC="$ROOT/skills/$SKILL_NAME"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
SKILLS_DIR="${CODEX_SKILLS_DIR:-$CODEX_HOME/skills}"
SKILL_DEST="$SKILLS_DIR/$SKILL_NAME"
VENV_DIR="${HTEXTRACT_VENV:-$ROOT/.venv}"
BIN_DIR="${HTEXTRACT_BIN_DIR:-$HOME/.local/bin}"

COPY_MODE=0
FORCE=0
INSTALL_TOOL=1
USE_UV_PIP=0

usage() {
  cat <<'EOF'
Usage: scripts/install-skill.sh [--copy] [--force] [--no-tool]

Installs the agent-session-trajectory Codex skill after git clone.

Defaults:
  - installs htextract into ./.venv
  - writes wrappers to ~/.local/bin/htextract and ~/.local/bin/agent-session-trajectory
  - symlinks skills/agent-session-trajectory into ${CODEX_HOME:-~/.codex}/skills

Options:
  --copy     Copy the skill instead of symlinking it.
  --force    Replace an existing installed skill at the destination.
  --no-tool  Only install the skill; do not create .venv or CLI wrappers.

Environment:
  CODEX_HOME          Codex home directory. Default: ~/.codex
  CODEX_SKILLS_DIR    Skill install directory. Default: $CODEX_HOME/skills
  HTEXTRACT_VENV      Tool venv directory. Default: <repo>/.venv
  HTEXTRACT_BIN_DIR   Wrapper directory. Default: ~/.local/bin
EOF
}

create_venv() {
  if python3 -m venv "$VENV_DIR"; then
    return 0
  fi

  echo "python3 -m venv failed; trying uv venv fallback..." >&2
  rm -rf "$VENV_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV_DIR"
    USE_UV_PIP=1
    return 0
  fi

  echo "could not create venv with python3 or uv" >&2
  echo "install uv or set HTEXTRACT_VENV to an existing Python venv" >&2
  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --copy)
      COPY_MODE=1
      ;;
    --force)
      FORCE=1
      ;;
    --no-tool)
      INSTALL_TOOL=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "skill source not found: $SKILL_SRC" >&2
  exit 1
fi

if [ "$INSTALL_TOOL" -eq 1 ]; then
  create_venv
  if [ "$USE_UV_PIP" -eq 1 ]; then
    uv pip install --python "$VENV_DIR/bin/python" -e "$ROOT"
  else
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -e "$ROOT"
  fi
fi

mkdir -p "$SKILLS_DIR"

if [ -e "$SKILL_DEST" ] || [ -L "$SKILL_DEST" ]; then
  if [ "$FORCE" -ne 1 ]; then
    echo "skill already exists: $SKILL_DEST" >&2
    echo "rerun with --force to replace it" >&2
    exit 1
  fi
  rm -rf "$SKILL_DEST"
fi

if [ "$COPY_MODE" -eq 1 ]; then
  cp -R "$SKILL_SRC" "$SKILL_DEST"
else
  ln -s "$SKILL_SRC" "$SKILL_DEST"
fi

if [ "$INSTALL_TOOL" -eq 1 ]; then
  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/htextract" <<EOF
#!/usr/bin/env sh
exec "$VENV_DIR/bin/htextract" "\$@"
EOF
  chmod +x "$BIN_DIR/htextract"

  cat > "$BIN_DIR/agent-session-trajectory" <<EOF
#!/usr/bin/env sh
HTEXTRACT="$VENV_DIR/bin/htextract" exec python3 "$SKILL_DEST/scripts/export_trajectory.py" "\$@"
EOF
  chmod +x "$BIN_DIR/agent-session-trajectory"
fi

echo "Installed skill: $SKILL_DEST"
if [ "$INSTALL_TOOL" -eq 1 ]; then
  echo "Installed htextract wrapper: $BIN_DIR/htextract"
  echo "Installed skill helper wrapper: $BIN_DIR/agent-session-trajectory"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Note: add $BIN_DIR to PATH if htextract is not found by your shell." ;;
  esac
fi
