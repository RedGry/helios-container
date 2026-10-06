# Качество кода

CI запускает проверки при каждом push и pull request. Релиз использует тот же
workflow `quality.yml`: неуспешная проверка блокирует сборку и создание черновика.
Версии PHP-инструментов зафиксированы в `composer.lock`, Rust в CI — 1.99.0.

## Rust

```sh
rustup toolchain install 1.99.0 --profile minimal --component rustfmt --component clippy
cargo +1.99.0 fmt --manifest-path native/Cargo.toml --all --check
cargo +1.99.0 clippy --manifest-path native/Cargo.toml --all-targets --all-features --locked -- -D warnings
cargo +1.99.0 test --manifest-path native/Cargo.toml --all-targets --all-features --locked
```

`rustfmt` задаёт единый стиль. Clippy проверяет корректность, подозрительные
конструкции, сложность и производительность; каждое предупреждение завершает
проверку ошибкой. Исправляйте причину вместо добавления `allow`.
`native/build.sh` также запускает Clippy на целевой FreeBSD.

## PHP

```sh
composer install
composer check
python3 -m unittest discover -s tests -p test_php_gateway.py -v
python3 tools/test_quality.py --php
```

`composer check` проверяет синтаксис, стиль PSR-12 и PHPStan уровня 8 без baseline
и исключений ошибок. `composer format` исправляет форматирование. CI проверяет
PHP 8.2–8.5. PHPStan получает значение установочного маркера `__HC_PORT__` через
отдельный bootstrap; шаблон установки и установленный шлюз сохраняют свой контракт.

HTTP-тесты запускают настоящий PHP-шлюз и локальный backend во временном каталоге.
Они проверяют методы и маршруты, передачу тела и query string, фильтрацию заголовков,
подмену служебных ключей, дублирующиеся cookies, HEAD, redirect, лимит тела и заголовки
безопасности. Рабочая VM не нужна.

`tools/test_quality.py` проверяет сами барьеры: корректный пример проходит,
нарушение стиля, ошибка типов, предупреждение Clippy и падающий тест дают ненулевой
код завершения. Для Rust используйте `python3 tools/test_quality.py --rust`
с выбранным toolchain 1.99.0.

## Ревью и защита main

Для `main` обязательны PR, актуальные успешные проверки `code-quality`, `scripts`
и `release-check` и разрешённые обсуждения. Для единственного сопровождающего
обязательное одобрение отключено: автор не может одобрить собственный PR.
Прямой push, force push и удаление ветки запрещены, включая
обход администраторами. Защита настраивается в GitHub, а не самим YAML-файлом.

Комментарии в новом коде не пишем: выбираем понятные имена, небольшие функции,
явные типы и тесты поведения. Линтеры не доказывают понятность архитектуры;
это проверяет человек на ревью. Документация процесса находится в Markdown.
