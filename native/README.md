# Rust runtime

Первый этап постепенного переноса helios-container. Это нативный CLI для существующей установки на FreeBSD amd64. Он использует прежние `config.json`, QMP-сокет, SSH-ключ и диск VM.

На Rust работают `start`, `stop`, `status`, `docker`, `ssh`, `upload`, `download`, `forward`, `configure`, `logs`, `profile` и `version`. Аргументы Docker передаются в гостевую систему с экранированием. Неизвестные поля конфигурации сохраняются.

`web`, `update`, `check-update` и `uninstall` пока выполняются совместимыми Python-модулями. Установщик, веб-агент, монитор автоостановки и PHP-шлюз сохраняются. Rust не заменяет QEMU и не даёт аппаратное ускорение VM. Этот этап не является полной миграцией на Rust.

## Сборка на FreeBSD

Нужны Cargo, Rust и системный C-компилятор. Студентам в будущих релизах будет достаточно готового бинарника, установка компилятора им не потребуется.

```sh
cd native
cargo test --locked
cargo build --release --locked
python3.11 tests/lifecycle.py target/release/helios-container-native
```

Последняя команда проверяет запуск, QMP-события, проброс порта, корректную остановку и сохранение неизвестных полей конфигурации на одноразовой fixture в системном временном каталоге. Работающая VM пользователя не используется.

В Linux можно запускать unit-тесты, но Linux-бинарник нельзя устанавливать на helios. Целевая система — FreeBSD 14 amd64. Бинарник должен быть собран и проверен на совместимой FreeBSD. Используются системные `libc`, `libthr` и `libgcc_s`, отдельные библиотеки из Cargo после сборки не нужны.

## Переключение существующей установки

Сначала сохраните бинарник как `~/.local/helios-container/helios-container-native` с правами `700`. Затем:

```sh
~/.local/helios-container/helios-container-native status
~/.local/helios-container/helios-container-native docker ps
~/.local/helios-container/helios-container-native adopt
helios-container version
```

`adopt` заменяет только два принадлежащих kit launcher-файла в `~/.local/bin`. Их исходное содержимое сохраняется в `helios-container.before-rust` и `docker.before-rust`. Посторонние файлы и ссылки заменять нельзя. VM не останавливается, её настройки, контейнеры и volumes сохраняются.

Откат:

```sh
~/.local/helios-container/helios-container-native rollback
```

Для нестандартного каталога добавьте `--base /полный/путь` перед командой. Версия установки читается из существующего `VERSION`, при его отсутствии показывается `dev`. Версия самого Rust runtime отображается отдельно и не создаёт GitHub-релиз.

Во время перехода не запускайте обновление из старого релизного пакета поверх Rust launcher-файлов. Старый установщик может вернуть команды на Python, после чего проверенный Rust runtime можно включить снова через `adopt`. Автоматический переход всех пользователей будет добавлен после переноса агента и согласования формата релизных архивов.
