Запуск Python

Запустить CLI (главное)	.\.venv\Scripts\python.exe cli.py
Запустить разовую команду	.\.venv\Scripts\python.exe -c "print('ok')"
Что установлено в venv	.\.venv\Scripts\python.exe -m pip list
Доставить библиотеку	.\.venv\Scripts\python.exe -m pip install tzdata
Пересоздать venv с нуля	Remove-Item .\.venv -Recurse -Force; python -m venv .venv
Активировать venv (опционально)	.\.venv\Scripts\Activate.ps1
Выйти из venv	deactivate

Управление файлами

Прочитать файл целиком	Get-Content config.yaml
Удалить файл	Remove-Item .\data\crossing.db
Удалить папку с содержимым	Remove-Item .\data -Recurse -Force
Скопировать/переместить	Copy-Item a b / Move-Item a b
Найти файл по имени	Get-ChildItem -Recurse -Filter "*.yaml"

Просмотр базы SQLite (без установки клиента)

Последние 10 наблюдений	.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/crossing.db'); [print(r) for r in c.execute('SELECT ts_utc,status,wait_min FROM observations ORDER BY id DESC LIMIT 10')]"
Сколько наблюдений	.\.venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('data/crossing.db').execute('SELECT COUNT(*) FROM observations').fetchone()[0])"