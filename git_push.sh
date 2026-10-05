#!/usr/bin/env bash
# Инициализация git и push в GitHub.
# Токен берётся из файла .token (в git не коммитится).
set -e
cd "$(dirname "$0")"

REPO="ukichan2285/schedule_sevsu_dz"
TOKEN="$(tr -d '\n\r' < .token)"

if [ -z "$TOKEN" ]; then
  echo "❌ Нет .token"
  exit 1
fi

git config user.name "ukichan2285"
git config user.email "ukichan2285@users.noreply.github.com"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -b main
fi

git add .
git commit -m "${1:-update}" || echo "нечего коммитить"

git remote remove origin 2>/dev/null || true
git remote add origin "https://${TOKEN}@github.com/${REPO}.git"

git push -u origin main 2>&1 | sed -E 's#(https://)[^@]*@#\1***@#g'
