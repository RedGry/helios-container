# Разработка

`main` — стабильная и целевая ветка PR. Рабочие ветки: `feature/<имя>`, `bugfix/<имя>` и `release/<версия>`; `develop` и префикс `codex/` не используются. Эта схема закреплена в `AGENTS.md` для всех чатов проекта.

Один PR решает одну задачу. Описание и пункты changelog пишите на русском. Пользовательские изменения добавляйте в `CHANGELOG.md` → `Unreleased`. Не включайте в Git диски VM, настройки и ключи.

## Проверки

На FreeBSD amd64:

```sh
sh native/build.sh
python3 native/tests/lifecycle.py native/target/release/helios-container-native
python3 native/tests/gateway.py native/target/release/helios-container-native
python3 -m unittest discover -s tests -v
node --test tests/*.cjs
php -l gateway.php
sh -n install.sh
git diff --check
```

Python и Node.js нужны для разработки. Тестовые стенды используют временную установку.

## Релиз

Согласуйте `VERSION` и `native/Cargo.toml`, перенесите готовые пункты из `Unreleased` в раздел выпуска.

```sh
python3 tools/release.py --check
python3 tools/release.py --binary native/target/release/helios-container-native
python3 tools/release.py --verify
```

Комплект в `dist/` содержит бинарник, SHA-256, `VERSION` и описание релиза. CI сохраняет предпросмотр в `release-preview`.

Ручной workflow `Release` на `main` создаёт черновик. Перед запуском проверьте отсутствие такого тега и релиза; перед публикацией — установку и сохранность данных при обновлении на FreeBSD.

Подробный процесс: [helios-release](.agents/skills/helios-release/SKILL.md).
