<?php

declare(strict_types=1);

return (new PhpCsFixer\Config())
    ->setRules(['@PSR12' => true])
    ->setFinder(PhpCsFixer\Finder::create()
        ->in(__DIR__)
        ->depth('== 0')
        ->name('*.php')
        ->ignoreDotFiles(false)
        ->append([__DIR__ . '/tools/phpstan-bootstrap.php']));
