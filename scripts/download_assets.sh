#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Downloading Apptronik Apollo model from MuJoCo Menagerie..."

git clone --depth 1 https://github.com/google-deepmind/mujoco_menagerie.git /tmp/menagerie

mkdir -p "$REPO_ROOT/assets"
cp -r /tmp/menagerie/apptronik_apollo "$REPO_ROOT/assets/"
rm -rf /tmp/menagerie

echo "Assets downloaded to $REPO_ROOT/assets/apptronik_apollo"
