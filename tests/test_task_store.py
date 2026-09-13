from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_store import load_tasks, save_task


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix='coffee-json-test-')) / 'tasks.json'
        self.task = dict(task_id='test-1', plot_id='CF001', task_type='irrigation',
                         scheduled_at='2030-01-01T07:00:00+07:00', notes='Tưới lô thử',
                         created_at='2026-09-13T07:00:00+07:00')

    def test_concurrent_duplicates_and_distinct_tasks(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: save_task(self.path, self.task), range(8)))
        self.assertEqual(sum(r['status'] == 'SUCCESS' for r in replies), 1)
        tasks = [{**self.task, 'task_id': f'test-{i}', 'scheduled_at': f'2030-02-{i:02d}T07:00:00+07:00'} for i in range(1, 9)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda task: save_task(self.path, task), tasks))
        self.assertEqual(len(load_tasks(self.path)), 9)

    def test_corrupt_file_is_preserved(self):
        with self.path.open('x', encoding='utf-8') as file:
            file.write('Không phải JSON')
        with self.assertRaises(ValueError):
            save_task(self.path, self.task)
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'Không phải JSON')

    def test_failed_replace_preserves_previous_tasks(self):
        save_task(self.path, self.task)
        before = self.path.read_bytes()
        with patch('task_store.os.replace', side_effect=OSError):
            with self.assertRaises(OSError):
                save_task(self.path, {**self.task, 'scheduled_at': '2030-03-01T07:00:00+07:00'})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(json.loads(before), [self.task])
