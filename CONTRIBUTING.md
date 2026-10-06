# Разработка

`main` — стабильная и целевая ветка PR. Рабочие ветки: `feature/<имя>`, `bugfix/<имя>` и `release/<версия>`; `develop` и префикс `codex/` не используются. Эта схема закреплена в `AGENTS.md` для всех чатов проекта.

Один PR решает одну задачу. Описание и пункты changelog пишите на русском. Пользовательские изменения добавляйте в `CHANGELOG.md` → `Unreleased`. Не включайте в Git диски VM, настройки и ключи.

## Проверки

На FreeBSD amd64:

```sh
sh native/build.sh
python3 native/tests/lifecycle.py native/target/release/helios-container-native
python3 native/tests/gateway.py native/target/release/helios-container-native
python3 native/tests/update.py native/target/release/helios-container-native
python3 -m unittest discover -s tests -v
node --test tests/*.cjs
php -l gateway.php
sh -n install.sh
git diff --check
```

Python и Node.js нужны для разработки. Тестовые стенды используют временную установку.

## Релиз

Подготовку ведите в `release/X.Y.Z` с PR в `main`. Если изменения уже слиты в `main`, их не нужно переносить заново: выпуск готовится из проверенного коммита; отдельный PR нужен для оставшихся изменений версии и changelog.

Согласуйте `VERSION` и `native/Cargo.toml`, перенесите готовые пункты из `Unreleased` в раздел выпуска.

```sh
python3 tools/release.py --check
python3 tools/release.py --binary native/target/release/helios-container-native
python3 tools/release.py --verify
```

Комплект в `dist/` содержит бинарник, SHA-256, `VERSION` и описание релиза. CI сохраняет предпросмотр в `release-preview`.

Ручной workflow `Release` на `main` создаёт черновик. Перед запуском проверьте отсутствие такого тега и релиза; перед публикацией — установку и сохранность данных при обновлении на FreeBSD.

Теги выпусков называются `vX.Y.Z`, например `v0.1.0`, и фиксируют конкретный проверенный коммит `main`. Заранее вручную тег не создаём: используем процесс выпуска и проверяем SHA черновика. Опубликованные теги и вложения не заменяем; исправление получает новую версию. Уведомления об обновлении появляются по опубликованному стабильному GitHub Release, а не по одному тегу.

Подробный процесс: [helios-release](.agents/skills/helios-release/SKILL.md).
