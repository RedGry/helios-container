#!/bin/sh
set -eu
if [ "$(uname -s)" != FreeBSD ] || [ "$(uname -m)" != amd64 ]; then
    echo 'Нужна FreeBSD amd64.' >&2
    exit 1
fi
umask 077
mkdir -p "$HOME/.local"
hc_temp=$(mktemp -d "$HOME/.local/helios-container-install.XXXXXXXX")
case "$hc_temp" in "$HOME"/.local/helios-container-install.*) ;; *) exit 1 ;; esac
trap 'rm -rf -- "$hc_temp"' EXIT HUP INT TERM
hc_release=https://github.com/RedGry/helios-container/releases/latest/download
if [ "${1:-}" = --source ]; then
    shift
    curl --proto '=https' --proto-redir '=https' -fL --retry 3 --max-time 120 \
        https://codeload.github.com/RedGry/helios-container/tar.gz/refs/heads/main -o "$hc_temp/source.tar.gz"
    tar -xzf "$hc_temp/source.tar.gz" -C "$hc_temp"
    hc_source="$hc_temp/helios-container-main/native"
    if ! command -v cargo >/dev/null 2>&1; then
        export CARGO_HOME="$hc_temp/cargo" RUSTUP_HOME="$hc_temp/rustup"
        curl --proto '=https' --proto-redir '=https' -fL --max-time 120 \
            https://sh.rustup.rs -o "$hc_temp/rustup-init.sh"
        sh "$hc_temp/rustup-init.sh" -y --profile minimal --no-modify-path
        PATH="$CARGO_HOME/bin:$PATH"
        export PATH
    fi
    (cd "$hc_source" && cargo build --release --locked)
    cp "$hc_source/../VERSION" "$hc_source/target/release/VERSION"
    "$hc_source/target/release/helios-container-native" install "$@"
else
    for hc_asset in helios-container-freebsd-amd64 helios-container-freebsd-amd64.sha256 VERSION; do
        curl --proto '=https' --proto-redir '=https' -fL --retry 3 --max-time 120 \
            "$hc_release/$hc_asset" -o "$hc_temp/$hc_asset" || {
            echo 'Нативный релиз пока недоступен. Можно собрать исходники с параметром --source.' >&2
            exit 1
        }
    done
    hc_line=$(cat "$hc_temp/helios-container-freebsd-amd64.sha256")
    hc_actual=$(sha256 -q "$hc_temp/helios-container-freebsd-amd64")
    [ "$hc_line" = "$hc_actual  helios-container-freebsd-amd64" ] || {
        echo 'SHA-256 не совпадает.' >&2
        exit 1
    }
    chmod 700 "$hc_temp/helios-container-freebsd-amd64"
    "$hc_temp/helios-container-freebsd-amd64" install "$@"
fi
