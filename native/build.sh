#!/bin/sh
set -eu
if [ "$(uname -s)" != FreeBSD ] || [ "$(uname -m)" != amd64 ]; then
    echo 'Сборка для helios должна выполняться на FreeBSD amd64.' >&2
    exit 1
fi
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cargo test --locked
cargo build --release --locked
printf '\nГотовый бинарник: %s/target/release/helios-container-native\n' "$PWD"
