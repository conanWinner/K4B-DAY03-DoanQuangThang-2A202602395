from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from schedule_confirmation import confirms_in_chat, schedule_confirmer
import test_web_ui
from tools import TIMEZONE


class ConfirmationTests(unittest.TestCase):
    def test_positive_negative_and_changed_proposal(self):
        for text in ['Tôi đồng ý lưu lịch', 'Đồng ý', 'Tôi đồng ý ghi lịch phun thuốc lô CF001 lúc 09:00 ngày 14/09/2026.']:
            self.assertTrue(confirms_in_chat(text))
        for text in ['Tôi chưa đồng ý lưu lịch', 'Không lưu nhé', 'Nếu tôi đồng ý thì sao?', 'Đồng ý, nhưng đừng lưu lịch']:
            self.assertFalse(confirms_in_chat(text))
        history = [{'role': 'tool', 'name': 'schedule_farm_task', 'result': {'proposed_task': {'plot_id': 'CF001'}}}]
        confirm = schedule_confirmer('Đồng ý', False, history)
        self.assertIsNone(confirm({'plot_id': 'CF002'}))
        self.assertTrue(confirm({'plot_id': 'CF001'}))
        self.assertIsNone(schedule_confirmer('Xin chào', False, history)({'plot_id': 'CF001'}))


class ConfirmationHTTPTests(unittest.TestCase):
    setUpClass = classmethod(test_web_ui.WebUITests.setUpClass.__func__)
    tearDownClass = classmethod(test_web_ui.WebUITests.tearDownClass.__func__)

    def test_chat_confirmation_without_checkbox_saves_json(self):
        args = dict(plot_id='CF001', task_type='irrigation_inspection', notes='Xác nhận qua chat',
                    scheduled_at=(datetime.now(TIMEZONE) + timedelta(days=1)).isoformat())

        class Provider:
            is_mock = True
            model_name = 'confirmation-regression'

            def generate_with_tools(self, history, *unused, **kwargs):
                if history[-1]['role'] == 'tool':
                    text = history[-1]['result']['status']
                    return {'calls': [], 'content': text, 'assistant': {'role': 'assistant', 'content': text}}
                return {'calls': [{'id': 'call', 'name': 'schedule_farm_task', 'arguments': args}],
                        'content': '', 'assistant': {'role': 'assistant', 'content': ''}}

        target = Path(tempfile.mkdtemp(prefix='coffee-confirm-test-')) / 'tasks.json'
        def send(message):
            request = Request(self.base + '/api/chat', method='POST', headers={'Content-Type': 'application/json'},
                data=json.dumps(dict(message=message, system_prompt='Trợ lý cà phê',
                                     session_id='confirmation-regression', allow_schedule=False)).encode())
            with urlopen(request, timeout=3) as response:
                return [json.loads(line) for line in response][-1]['answer']

        with patch.dict(os.environ, {'FARM_TASKS_FILE': str(target)}), patch('web_server.get_llm_provider', return_value=Provider()):
            self.assertEqual(send('Lập lịch kiểm tra tưới'), 'CONFIRMATION_REQUIRED')
            self.assertFalse(target.exists())
            self.assertEqual(send('Tôi đồng ý lưu lịch'), 'SUCCESS')
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))[0]['notes'], args['notes'])
            self.assertEqual(send('Tôi đồng ý lưu lịch'), 'ALREADY_EXISTS')
            self.assertEqual(len(json.loads(target.read_text(encoding='utf-8'))), 1)
