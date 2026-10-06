#!/bin/sh
set -eu
if [ "$(uname -s)" != FreeBSD ] || [ "$(uname -m)" != amd64 ]; then
    echo 'Сборка для helios должна выполняться на FreeBSD amd64.' >&2
    exit 1
fi
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cargo test --locked
cargo fmt --check
cargo build --release --locked
[ "$(./target/release/helios-container-native --build-version)" = "$(cat ../VERSION)" ]
cp ../VERSION target/release/VERSION
printf '\nГотовый бинарник: %s/target/release/helios-container-native\n' "$PWD"
