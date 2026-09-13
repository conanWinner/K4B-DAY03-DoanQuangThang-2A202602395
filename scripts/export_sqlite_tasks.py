"""Xuất lịch SQLite sang JSON mới, giữ nguyên SQLite và từ chối ghi đè đích."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def export_tasks(source, target):
    source, target = Path(source).resolve(), Path(target)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tasks = [dict(row) for row in connection.execute(
            'SELECT task_id, plot_id, task_type, scheduled_at, notes, created_at FROM farm_tasks ORDER BY created_at, task_id')]
    text = json.dumps(tasks, ensure_ascii=False, indent=2) + '\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as file:
        file.write(text)
    if json.loads(target.read_text(encoding='utf-8')) != tasks:
        raise RuntimeError('Dữ liệu xuất chưa khớp.')
    return len(tasks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('target')
    args = parser.parse_args()
    print(f'Đã chuyển {export_tasks(args.source, args.target)} lịch sang JSON. SQLite gốc được giữ nguyên.')
