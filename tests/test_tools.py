"""Chạy: .venv/bin/python -m unittest discover -s tests -v"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import tools


def call(name, **args):
    return json.loads(tools.dispatch_tool_call(name, args))


class ToolTests(unittest.TestCase):
    def test_plot_and_unknown(self):
        self.assertEqual(call('get_plot_info', plot_id=' cf001 ')['data_source'], 'SIMULATED')
        self.assertEqual(call('get_plot_info', plot_id='CF999')['status'], 'NOT_FOUND')
        self.assertEqual(call('unknown')['status'], 'UNKNOWN_TOOL')

    def test_validation_prevents_network(self):
        with patch.object(tools.requests, 'get') as get:
            for args in ({'latitude': 91, 'longitude': 108, 'days': 3},
                         {'latitude': 12, 'longitude': 108, 'days': True},
                         {'latitude': float('nan'), 'longitude': 108, 'days': 3}):
                self.assertEqual(call('get_weather_forecast', **args)['status'], 'INVALID_ARGUMENTS')
            get.assert_not_called()
        self.assertEqual(call('get_plot_info')['status'], 'INVALID_ARGUMENTS')
        self.assertEqual(call('get_plot_info', plot_id='CF001', extra=1)['status'], 'INVALID_ARGUMENTS')

    def test_weather_error_not_fake_success(self):
        with patch.object(tools.requests, 'get', side_effect=requests.Timeout):
            self.assertEqual(call('get_weather_forecast', latitude=12, longitude=108, days=3)['status'], 'WEATHER_ERROR')

    def test_weather_parsing(self):
        future = (datetime.now(tools.TIMEZONE) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        payload = {'hourly': {'time': [future.replace(tzinfo=None).isoformat()]}, 'hourly_units': {}}
        for field in tools.WEATHER_FIELDS:
            payload['hourly'][field] = [1.0]
            payload['hourly_units'][field] = 'test-unit'
        with patch.object(tools.requests, 'get') as get:
            get.return_value.json.return_value = payload
            result = call('get_weather_forecast', latitude=12, longitude=108, days=3)
            self.assertEqual(result['status'], 'SUCCESS')
            self.assertEqual(len(result['hourly']), 1)
            self.assertIsNone(result['model_updated_at'])
            payload['hourly']['precipitation'] = [None]
            self.assertEqual(call('get_weather_forecast', latitude=12, longitude=108, days=3)['status'], 'WEATHER_ERROR')

    def test_persistence_duplicates_and_invalid_schedule(self):
        # Giữ thư mục thử nghiệm; không xóa dữ liệu sau test.
        db = Path(tempfile.mkdtemp(prefix='coffee-tool-test-')) / 'tasks.json'
        args = dict(plot_id='CF001', task_type='irrigation_inspection',
                    scheduled_at=(datetime.now(tools.TIMEZONE) + timedelta(days=1)).isoformat(), notes='Kiểm tra đầu tưới')
        with patch.dict(os.environ, {'FARM_TASKS_FILE': str(db)}):
            self.assertEqual(call('schedule_farm_task', **{**args, 'plot_id': 'CF999'})['status'], 'NOT_FOUND')
            self.assertFalse(db.exists())
            self.assertEqual(call('schedule_farm_task', **{**args, 'scheduled_at': '2020-01-01T07:00:00+07:00'})['status'], 'INVALID_ARGUMENTS')
            self.assertEqual(call('schedule_farm_task', **{**args, 'scheduled_at': '2030-01-01T07:00:00'})['status'], 'INVALID_ARGUMENTS')
            first = call('schedule_farm_task', **args)
            self.assertEqual(first['status'], 'SUCCESS')
            second = call('schedule_farm_task', **args)
            self.assertEqual(second['status'], 'ALREADY_EXISTS')
            self.assertEqual(first['task']['task_id'], second['task_id'])
            rows = json.loads(db.read_text(encoding='utf-8'))
            self.assertEqual([r['notes'] for r in rows], ['Kiểm tra đầu tưới'])
            self.assertIn('Kiểm tra đầu tưới', db.read_text(encoding='utf-8'))

    def test_storage_error(self):
        with patch.object(tools, 'save_task', side_effect=OSError):
            args = dict(plot_id='CF001', task_type='irrigation',
                        scheduled_at=(datetime.now(tools.TIMEZONE) + timedelta(days=1)).isoformat(), notes='')
            self.assertEqual(call('schedule_farm_task', **args)['status'], 'STORAGE_ERROR')


if __name__ == '__main__':
    unittest.main()
