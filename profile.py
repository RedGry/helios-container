#!/usr/bin/env python3
"""Add the managed PATH block without replacing the user's profile."""
from pathlib import Path
from runtime import profile_edit

if __name__ == '__main__':
    base = Path.home() / '.local/helios-container'
    if not base.is_dir():
        raise SystemExit('Сначала установите helios-container.')
    profile_edit(base=base)
    print('Готово. Выполните: . ~/.profile')
