<h1 align="center">Helios Container</h1>
<p align="center">Docker для студентов на helios — без прав администратора.</p>

Личная Linux VM внутри FreeBSD: запускайте Docker-образы и Compose под своим аккаунтом. CPU, память и файлы VM учитываются вашему пользователю.

---

## Быстрый старт

Подключитесь к helios и выполните **одну команду**:

```sh
curl -fsSL https://raw.githubusercontent.com/RedGry/helios-container/main/install.sh | sh && . "$HOME/.profile"
```

Установщик скачает QEMU и Alpine Linux, настроит Docker, дождётся готовности VM и добавит команды в PATH. Первая установка занимает несколько минут.

Если репозиторий уже клонирован на helios, достаточно `python3.11 installer.py && . "$HOME/.profile"` из его каталога.

```sh
docker run --rm hello-world
docker ps
docker compose version
```

При последующих входах `docker` доступен сразу. Если VM остановлена, первая команда `docker` запустит её и дождётся загрузки.

## Ваше приложение

```sh
docker run -d --name web --restart unless-stopped -p 8080:80 nginx:alpine
helios-container forward 8080 28080
```

На своём компьютере откройте SSH-туннель, заменив `USERNAME` на свой логин:

```sh
ssh -p 2222 -N -L 8080:127.0.0.1:28080 USERNAME@se.ifmo.ru
```

Теперь приложение доступно на [localhost:8080](http://localhost:8080). Если порт `28080` занят, выберите другой или выполните `helios-container forward 8080` — свободный порт будет выбран автоматически.

## Управление

```sh
helios-container status
helios-container stop
helios-container start
helios-container ssh
```

По умолчанию: **1 CPU · 1 ГиБ RAM · диск до 12 ГиБ**. Диск растёт по мере записи. Для увеличения ресурсов:

```sh
helios-container stop
helios-container configure --memory 4096 --cpus 2
helios-container start
```

## Что важно знать

- Нужны FreeBSD 14.x amd64, Python ≥ 3.11 и стандартные инструменты helios.
- CPU эмулируется через QEMU TCG: сборки и тяжёлые приложения работают медленнее.
- Это Docker внутри VM: bind mounts и Compose-пути относятся к **Linux**, а не к домашней папке helios. Для файлов есть `upload` и `download`.
- Порты доступны через `forward` и SSH-туннель; автоматической публикации в интернете нет.
- У каждого пользователя отдельные диск, SSH-ключ и порт. Kit не обходит квоты и ограничения сервера.
- VM переживает выход из SSH, но после перезагрузки helios запускается первой командой `docker`.

[Файлы, Compose, очистка и диагностика →](docs/guide.md)

Все файлы установки — в `~/.local/helios-container`, команды — в `~/.local/bin`. Проверенная свежая установка занимает **около 225 МБ на ZFS**, включая Docker и маленький тестовый образ; ваши образы увеличат размер. Временные пакеты удаляются, сохраняется только нужная часть QEMU. В `~/.profile` добавляется блок PATH с резервной копией.

MIT · [Лицензия](LICENSE)
