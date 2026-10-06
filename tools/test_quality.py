import argparse
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def expect(command, success, cwd=ROOT):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if (result.returncode == 0) != success:
        raise RuntimeError(f'Unexpected gate result: {command}\n{result.stdout}\n{result.stderr}')


def php_gates(directory):
    fixture = directory / 'fixture.php'
    fixer = ['php', str(ROOT / 'vendor/bin/php-cs-fixer'), 'fix', str(fixture),
             '--config=' + str(ROOT / '.php-cs-fixer.dist.php'), '--path-mode=override',
             '--dry-run', '--using-cache=no']
    stan = ['php', str(ROOT / 'vendor/bin/phpstan'), 'analyse', str(fixture),
            '--configuration=' + str(ROOT / 'phpstan.neon'), '--no-progress']
    fixture.write_text('<?php\n\ndeclare(strict_types=1);\n\necho strlen("valid");\n')
    expect(['php', '-l', str(fixture)], True)
    expect(fixer, True)
    expect(stan, True)
    fixture.write_text('<?php echo strlen("valid");')
    expect(fixer, False)
    fixture.write_text('<?php\n\ndeclare(strict_types=1);\n\necho strlen([]);\n')
    expect(stan, False)
    fixture.write_text('<?php syntax error')
    expect(['php', '-l', str(fixture)], False)


def rust_gates(directory):
    (directory / 'src').mkdir()
    (directory / 'Cargo.toml').write_text('[package]\nname = "quality-fixture"\nversion = "0.1.0"\nedition = "2021"\n')
    source = directory / 'src/main.rs'
    source.write_text('fn main() {\n    println!("valid");\n}\n')
    expect(['cargo', 'fmt', '--check'], True, directory)
    expect(['cargo', 'clippy', '--all-targets', '--', '-D', 'warnings'], True, directory)
    source.write_text('fn main(){println!("valid");}')
    expect(['cargo', 'fmt', '--check'], False, directory)
    source.write_text('fn main() {\n    let values = [1];\n    if values.len() == 0 {\n        println!("empty");\n    }\n}\n')
    expect(['cargo', 'clippy', '--all-targets', '--', '-D', 'warnings'], False, directory)
    source.write_text('fn main() {}\n#[test]\nfn failure() { assert_eq!(1, 2); }\n')
    expect(['cargo', 'test'], False, directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', action='store_true')
    parser.add_argument('--rust', action='store_true')
    args = parser.parse_args()
    if not args.php and not args.rust:
        parser.error('Select --php or --rust')
    with tempfile.TemporaryDirectory(prefix='helios-quality-') as temp:
        directory = Path(temp)
        if args.php:
            php_gates(directory)
        if args.rust:
            rust_gates(directory)
    print('Quality gates accept valid code and reject broken fixtures.')


if __name__ == '__main__':
    main()
