# Разработка

`main` содержит стабильный код, `develop` используется для интеграции. Для работы используйте `feature/<имя>`, `bugfix/<имя>` или `release/X.Y.Z`. Ветки с префиксом `codex/` в проекте не используются.

Установленный kit работает без Python. Python 3.11 нужен только для тестовых стендов и упаковки релиза, Node.js — для тестов интерфейса.

На FreeBSD 14 amd64:

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

Тестовые стенды создают временную установку и не управляют рабочей VM. Локальные настройки, диски и ключи не должны попадать в Git.

## Подготовка релиза

Согласуйте `VERSION` и `native/Cargo.toml`, добавьте русский раздел версии в `CHANGELOG.md`. Используйте единственный сборщик:

```sh
python3 tools/release.py --check
python3 tools/release.py --binary native/target/release/helios-container-native
python3 tools/release.py --verify
```

В `dist/` появятся бинарник FreeBSD amd64, его SHA-256, `VERSION` и описание релиза. Проверки `scripts` и `release-check` выполняются при push и PR, комплект можно скачать из артефакта `release-preview`.

Ручной workflow `Release` на `main` создаёт только черновик с тегом `vX.Y.Z`. Обычный push не создаёт релиз. Перед запуском проверьте отсутствие такого тега и релиза. Публикация черновика выполняется отдельно, после проверки установки и сохранности данных при обновлении на FreeBSD.
