# Руководство

Установка описана в [README](../README.md). Команды ниже выполняются на helios, если не указано другое.

Docker работает внутри Linux VM. Пути к файлам относятся к VM; домашняя папка helios автоматически не подключается. CPU эмулируется через QEMU, поэтому сборки и запуск тяжёлых приложений могут занимать несколько минут. Квоты аккаунта продолжают действовать.

## Управление VM

```sh
helios-container status
helios-container stop
helios-container start
helios-container ssh
```

VM продолжает работать после выхода из SSH. После перезагрузки helios её запустит первая команда `docker`.

По умолчанию выделены 1 CPU, 1 ГиБ RAM и диск до 12 ГиБ. Диск растёт по мере записи. Чтобы изменить CPU и память:

```sh
helios-container stop
helios-container configure --memory 4096 --cpus 2
helios-container start
```

Ресурсы VM расходуют квоту пользователя; выделенные vCPU не гарантируют долю CPU сервера. Поддерживаются Linux-образы amd64.

## Файлы и Compose

Загрузите проект в VM и запустите его:

```sh
helios-container upload ./my-app /workspace
docker compose -f /workspace/my-app/compose.yaml up -d
docker compose -f /workspace/my-app/compose.yaml logs -f
```

Есть готовый [пример nginx + Compose](../examples/web/compose.yaml). Относительные пути в Compose отсчитываются от файла внутри VM. Для постоянных данных используйте volumes.

```sh
helios-container download /workspace/my-app ./backup
```

`docker build .`, `docker cp` и `--env-file` также ищут файлы в VM. Для сборки можно передать архив с helios:

```sh
tar -C ./my-app -czf - . | docker build -t my-app -
```

Архив включает все файлы каталога: заранее исключите секреты и лишние файлы.

Для ожидания готовности сервисов настройте `healthcheck` и используйте `docker compose up --wait`.

## Доступ к приложению

Опубликуйте порт контейнера и пробросьте его на helios:

```sh
docker run -d --name web --restart unless-stopped -p 8080:80 nginx:alpine
helios-container forward 8080 28080
```

Первый аргумент `forward` — порт VM, второй — свободный порт helios. Если второй аргумент пропущен, порт выбирается автоматически. Проброс сохраняется после перезапуска VM.

На своём компьютере откройте туннель, заменив `USERNAME` своим логином:

```sh
ssh -p 2222 -N -L 8080:127.0.0.1:28080 USERNAME@se.ifmo.ru
```

Приложение доступно на [localhost:8080](http://localhost:8080). Для HTTPS без туннеля используйте [веб-шлюз](web.md).

## Автоостановка

VM выключается после 30 минут без обращений к опубликованным TCP-портам. SSH-туннели и HTTPS-запросы сбрасывают таймер; обновление панели — нет. Команды `docker`, `ssh`, `upload` и `download` защищены от автоостановки до завершения.

Для длительных задач без сетевого трафика отключите автоостановку:

```sh
helios-container configure --auto-stop off
```

Чтобы включить её снова, используйте `--auto-stop on`. Настройка применяется без перезапуска.

После остановки данные сохраняются. Команда `docker` запускает VM; контейнеры с политикой `always` или `unless-stopped` запускаются вместе с Docker.

## Обновление

```sh
helios-container check-update
helios-container stop
helios-container update
```

Обновление проверяет контрольную сумму и сохраняет диск, контейнеры, volumes, ключи и настройки. QEMU и Docker внутри VM не переустанавливаются. После обновления повторите нужную команду.

## Место на диске

```sh
docker system df
docker system prune -af
helios-container ssh 'fstrim -v /'
```

`prune -af` удаляет остановленные контейнеры, неиспользуемые образы, сети и кеш сборки. Volumes сохраняются. `fstrim` освобождает блоки диска VM; результат зависит от файловой системы хоста.

## Диагностика

```sh
helios-container status
helios-container logs
helios-container ssh 'tail -n 60 /var/log/docker.log'
```

Если VM ещё загружается, дождитесь готовности. `stop --force` принудительно завершает QEMU и может повредить данные.

Установка находится в `~/.local/helios-container`, команды — в `~/.local/bin`. Установщик добавляет PATH в `~/.profile`; для другой оболочки настройте PATH в её конфигурации.

## Удаление

Сначала сохраните нужные файлы через `download`:

```sh
helios-container stop
helios-container uninstall --yes
```

Удаление уничтожает диск VM, контейнеры, образы и volumes.
