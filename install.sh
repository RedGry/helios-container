#!/bin/sh
set -eu

if [ "$(uname -s)" != FreeBSD ] || [ "$(uname -m)" != amd64 ]; then
    echo 'helios-container предназначен для FreeBSD amd64.' >&2
    exit 1
fi

hc_python=''
for candidate in python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
        hc_python=$(command -v "$candidate")
        break
    fi
done
if [ -z "$hc_python" ]; then
    echo 'Нужен Python 3.11 или новее. На helios он доступен как python3.11.' >&2
    exit 1
fi

mkdir -p "$HOME/.local"
hc_temp=$(mktemp -d "$HOME/.local/helios-container-install.XXXXXXXX")
case "$hc_temp" in "$HOME"/.local/helios-container-install.*) ;; *) exit 1 ;; esac
trap 'rm -rf -- "$hc_temp"' EXIT HUP INT TERM
if [ -n "${GH_TOKEN:-}" ]; then
    printf 'Authorization: Bearer %s\n' "$GH_TOKEN" | \
        curl -fL --retry 3 --connect-timeout 15 --max-time 120 -H @- \
        https://api.github.com/repos/RedGry/helios-container/tarball/main \
        -o "$hc_temp/source.tar.gz"
else
    curl -fL --retry 3 --connect-timeout 15 --max-time 120 \
        https://codeload.github.com/RedGry/helios-container/tar.gz/refs/heads/main \
        -o "$hc_temp/source.tar.gz"
fi
unset GH_TOKEN
tar -xzf "$hc_temp/source.tar.gz" -C "$hc_temp"
hc_source=''
for candidate in "$hc_temp"/*/installer.py; do
    if [ -f "$candidate" ]; then hc_source=$candidate; break; fi
done
if [ -z "$hc_source" ]; then echo 'В архиве не найден installer.py.' >&2; exit 1; fi
"$hc_python" "$hc_source" "$@"
