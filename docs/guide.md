# Руководство

## Требования и установка

Kit проверяется на helios с FreeBSD 14.x amd64. Нужны Python ≥ 3.11, `pkg`, `curl`, `tar`, `makefs`, `ssh`, `scp`, `ssh-keygen`, `ldd` и доступ к HTTPS-репозиториям GitHub, FreeBSD и Alpine. На этапе установки нужно около 2 ГиБ свободного места: пакеты сначала распаковываются, затем временные файлы удаляются. На других ОС установщик завершится с объяснением.

По умолчанию VM получает 1024 МиБ RAM, 1 vCPU и виртуальный диск 12 ГиБ. Это настройки гостя; расход памяти QEMU на хосте включает служебную память и может быть больше. Физический размер qcow2 определяется содержимым, сжатием ZFS и количеством скачанных Docker-образов.

Можно задать начальные ресурсы:

```sh
curl -fsSL https://raw.githubusercontent.com/RedGry/helios-container/main/install.sh | sh -s -- --memory 2048 --cpus 2 --disk 16
. "$HOME/.profile"
```

Повторная установка сохраняет существующий диск, ключи и настройки; параметры `--memory`, `--cpus`, `--disk` задают только новую установку. Для существующей VM используйте `configure`. Автоматического обновления QEMU, Alpine и Docker нет.

Из клона можно запустить `python3.11 installer.py --memory 2048 --cpus 2 --disk 16`.

## PATH

Установщик добавляет в `.profile` отдельный блок:

```sh
# >>> helios-container >>>
export PATH="$HOME/.local/bin:$PATH"
# <<< helios-container <<<
```

Остальные настройки сохраняются. Исходная копия — `~/.local/helios-container/profile.before`. Повторный запуск не дублирует блок. Отдельная команда для повторной настройки: `helios-container profile`.

Для текущей сессии выполните `. "$HOME/.profile"`. Если ваша оболочка читает `.bash_profile` или конфигурацию zsh вместо `.profile`, добавьте туда тот же PATH самостоятельно. Имена чужих файлов `~/.local/bin/docker` и `helios-container` установщик не перезаписывает. Команда `docker` здесь является обёрткой над CLI внутри Linux VM; это не нативный Docker Engine FreeBSD.

## Файлы и Docker Compose

В VM есть `/workspace`. Загрузите проект с helios:

В репозитории есть готовый [пример nginx + Compose](../examples/web/compose.yaml).

```sh
helios-container upload ./my-app /workspace
docker compose -f /workspace/my-app/compose.yaml up -d
docker compose -f /workspace/my-app/compose.yaml logs -f
```

Пути `./data` в Compose отсчитываются от файла Compose **внутри VM**. Домашняя папка helios автоматически не подключается. Для постоянных данных удобны Docker volumes; они хранятся на диске VM и переживают её перезапуск.

```sh
helios-container download /workspace/my-app ./backup
```

Сборка из домашней папки возможна через стандартный ввод:

```sh
tar -C ./my-app -czf - . | docker build -t my-app -
```

В этом примере tar отправляет все файлы каталога: исключите секреты и ненужные файлы перед отправкой. `docker build .`, `docker cp ./file ...` и локальный `--env-file` ищут файлы в VM. Для таких команд сначала используйте `upload`.

## Порты

У сети три слоя: контейнер → Linux VM → loopback helios → SSH-туннель на компьютер.

```sh
docker run -d --name web -p 8080:80 nginx:alpine
helios-container forward 8080 28080
```

`forward` добавляет TCP-проброс без перезапуска работающей VM и сохраняет его для следующих запусков. Первый аргумент — порт Linux VM, второй — свободный порт helios ≥ 1024. Без второго аргумента порт выбирается автоматически. UDP и удаление пробросов отдельной командой пока не поддерживаются; список находится в `config.json`, менять его можно при остановленной VM.

```sh
# На вашем компьютере:
ssh -p 2222 -N -L 8080:127.0.0.1:28080 USERNAME@se.ifmo.ru
```

SSH гостя тоже доступен только через loopback helios, на индивидуальном порту из `helios-container status`. Docker API по TCP не открывается.

## Ресурсы и ограничения

```sh
helios-container stop
helios-container configure --memory 4096 --cpus 2
helios-container start
docker run --rm --memory=64m --cpus=0.5 hello-world
```

Число vCPU задаёт параллелизм гостя, а не гарантированную долю CPU физического сервера. На хосте работает пользовательский процесс QEMU. На него распространяются лимиты FreeBSD, включая RCTL и login class; права root внутри гостя не дают прав администратора helios. Размер виртуального диска не резервируется целиком и не заменяет квоту пользователя.

Kit не снимает ограничения сервера. Квоты разных аккаунтов могут отличаться. На одном проверенном аккаунте краткие тесты успешно выделили и записали 8 ГиБ RAM и использовали почти 4 CPU в течение 15 секунд. Это нижние границы для этого аккаунта, а не обещание ресурсов всем студентам и не доказательство отсутствия длительных ограничений. Точные правила RCTL могут быть недоступны обычному пользователю.

Поддерживаются Linux-образы amd64. Windows-контейнеры и аппаратное ускорение GPU/KVM/bhyve не предусмотрены. Обычная работа образов и Compose проверяется отдельно от совместимости конкретного приложения; приложениям могут потребоваться дополнительные память, диск или Linux-модули.

Rootless Docker на FreeBSD напрямую kit не устанавливает: Linux Engine работает внутри гостевой ОС. У другого пользователя должен быть собственный экземпляр установки. Использование чужой VM расходует ресурсы её владельца.

Обычно загрузка занимает несколько минут. При `docker` после остановки VM обёртка ждёт готовности до 10 минут. Интерактивные команды `docker run -it` работают из интерактивной SSH-сессии.

## Место на диске

Логи новых контейнеров используют драйвер `local`: до 3 файлов по 10 МиБ на контейнер. Сам Docker всё равно хранит образы, volumes и build cache; размеры приложения ничем автоматически не ограничиваются.

```sh
docker system df
docker system prune -af
helios-container ssh 'fstrim -v /'
du -sh ~/.local/helios-container
```

`prune -af` удаляет остановленные контейнеры, неиспользуемые образы, сети и build cache. Volumes эта команда сохраняет. `fstrim` сообщает qcow2 об освобождённых блоках; фактическое освобождение места зависит от файловой системы хоста и ZFS snapshots.

## Диагностика

```sh
helios-container status
helios-container logs
helios-container ssh 'cloud-init status --long'
helios-container ssh 'tail -n 60 /root/install-docker.log'
helios-container ssh 'tail -n 60 /var/log/docker.log'
```

Если VM не отвечает, сначала дождитесь загрузки. `stop` ждёт корректного выключения до 2 минут; `stop --force` завершает процесс QEMU без корректного выключения и может повредить данные гостя.

При конфликте SSH-порта:

```sh
helios-container stop
helios-container configure --ssh-port 28123
helios-container start
```

Не выключайте проверку SSH host key при неожиданном сообщении о смене ключа. Сначала убедитесь, что это действительно ваш заново созданный гость.

## Удаление

```sh
helios-container stop
helios-container uninstall --yes
```

Удаление уничтожает диск VM, контейнеры, образы и volumes. Предварительно выгрузите нужные файлы через `download`. Удаляются только каталог kit, его команды и управляемый блок PATH; остальные файлы домашней папки сохраняются.

## Источники

- [QEMU: TCG и поддерживаемые хосты](https://www.qemu.org/docs/master/system/introduction.html)
- [QEMU: сеть пользователя и hostfwd](https://www.qemu.org/docs/master/system/invocation.html)
- [FreeBSD: ограничения ресурсов](https://docs.freebsd.org/en/books/handbook/security/#security-resourcelimits)
- [Alpine Linux cloud images](https://alpinelinux.org/cloud/)
- [Docker: работа с диском](https://docs.docker.com/reference/cli/docker/system/prune/)
