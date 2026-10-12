set -eu
if [ ! -f /root/docker-ready ]; then
    echo 'Первичная установка Docker ещё не завершена; оптимизация отменена.' >&2
    exit 1
fi
docker info >/dev/null
finish_bootstrap=false
if [ "${HC_FINISH_BOOTSTRAP:-0}" = 1 ] && apk info -e cloud-init >/dev/null 2>&1; then
    finish_bootstrap=true
    finished=false
    for attempt in $(seq 1 120); do
        if [ -f /var/lib/cloud/instance/boot-finished ] && ! pgrep -f '/usr/bin/cloud-init (init|modules)' >/dev/null; then
            finished=true
            break
        fi
        sleep 1
    done
    if [ "$finished" != true ]; then
        echo 'cloud-init ещё работает; пакеты сохранены. Повторите helios-container optimize позже.' >&2
        exit 1
    fi
fi
if [ ! -f /etc/network/interfaces.helios-before ]; then
    cp -p /etc/network/interfaces /etc/network/interfaces.helios-before
fi
sed -i '/^iface eth0 inet6 dhcp$/d' /etc/network/interfaces
mkdir -p /etc/cloud
touch /etc/cloud/cloud-init.disabled
for entry in cloud-init-local:boot cloud-init:default cloud-config:default cloud-final:default cloud-init-hotplugd:default; do
    service=${entry%:*}
    runlevel=${entry#*:}
    if [ -L "/etc/runlevels/$runlevel/$service" ]; then
        rc-update del "$service" "$runlevel"
    fi
done
if [ "$finish_bootstrap" = true ]; then
    if [ ! -f /root/apk-world.helios-before ]; then
        cp -p /etc/apk/world /root/apk-world.helios-before
    fi
    apk add --no-network ifupdown-ng-iproute2
    if [ -x /etc/init.d/cloud-init-hotplugd ] && rc-service cloud-init-hotplugd status >/dev/null 2>&1; then
        rc-service cloud-init-hotplugd stop
    fi
    apk del cloud-init
fi
apk --no-network cache clean
sync
fstrim -v /
printf '%s\n' 'Первичная настройка cloud-init отключена. Docker и SSH сохранены. Изменения запуска применятся после перезапуска VM.'
