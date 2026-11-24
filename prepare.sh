#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
repo="${1:-$HOME/mova_nutripal/dreame-vacuum}"
commit=fec086caf064f2681e8bcc7be20a0d0ef54f444d
src=custom_components/dreame_vacuum/dreame
dest=custom_components/mova_nutripal/dreame_cloud
# Export only the exact tested upstream revision, never credentials or logs.
git -C "$repo" cat-file -e "$commit^{commit}"
mkdir -p "$dest"
for f in protocol.py exceptions.py types.py; do
    git -C "$repo" show "$commit:$src/$f" > "$dest/$f"
    if [[ -f "$HOME/mova_nutripal/dreame_cloud/$f" ]]; then
        cmp "$dest/$f" "$HOME/mova_nutripal/dreame_cloud/$f" || { echo "Local tested file differs: $f; review before publishing" >&2; exit 1; }
    fi
done
touch "$dest/__init__.py"
git -C "$repo" show "$commit:LICENSE" > "$dest/LICENSE"
test -s "$dest/LICENSE"
echo 'Vendored transport and upstream license ready. Review before git add.'
