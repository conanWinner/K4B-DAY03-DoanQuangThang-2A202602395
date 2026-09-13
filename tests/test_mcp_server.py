"""Kiểm tra cầu nối MCP với tool thật và các lỗi ở ranh giới dispatcher."""
from contextlib import closing
from datetime import datetime, timedelta
import os
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mcp_server import MCPAcademicServer, MCPFarmServer
from tools import TIMEZONE, WEATHER_FIELDS


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.server = MCPFarmServer()

    def test_registry_and_compatibility(self):
        schemas = self.server.list_tools()
        self.assertEqual({t['name'] for t in schemas},
                         {'get_plot_info', 'get_weather_forecast', 'schedule_farm_task'})
        schemas[0]['parameters']['properties'].clear()
        self.assertTrue(self.server.list_tools()[0]['parameters']['properties'])
        self.assertIs(MCPAcademicServer, MCPFarmServer)

    def test_plot_envelope(self):
        reply = self.server.call_tool('get_plot_info', {'plot_id': 'CF001'})
        self.assertEqual(reply['jsonrpc'], '2.0')
        self.assertEqual(reply['server'], 'coffee-farm-mcp-server')
        self.assertEqual(reply['tool'], 'get_plot_info')
        self.assertEqual(reply['result']['status'], 'SUCCESS')
        self.assertEqual(reply['result']['data']['latitude'], 12.6667)

    def test_business_errors_preserved(self):
        for name, args, status in [
            ('get_plot_info', {'plot_id': 'CF999'}, 'NOT_FOUND'),
            ('get_plot_info', {}, 'INVALID_ARGUMENTS'),
            ('get_plot_info', None, 'INVALID_ARGUMENTS'),
            ('missing_tool', {}, 'UNKNOWN_TOOL'),
        ]:
            with self.subTest(status=status, args=args):
                self.assertEqual(self.server.call_tool(name, args)['result']['status'], status)

    def test_weather_dispatch_and_failure(self):
        args = {'latitude': 12.6667, 'longitude': 108.05, 'days': 3}
        future = (datetime.now(TIMEZONE) + timedelta(days=1)).replace(tzinfo=None).isoformat()
        hourly = {'time': [future], **{field: [1] for field in WEATHER_FIELDS}}
        with patch('tools.requests.get') as get:
            get.return_value.json.return_value = {
                'hourly': hourly, 'hourly_units': {field: 'test' for field in WEATHER_FIELDS}}
            reply = self.server.call_tool('get_weather_forecast', args)['result']
            self.assertEqual(reply['status'], 'SUCCESS')
            self.assertEqual(reply['hourly'][0]['precipitation'], 1)
            self.assertEqual(get.call_args.kwargs['params']['latitude'], args['latitude'])
        with patch('tools.requests.get', side_effect=requests.Timeout):
            self.assertEqual(self.server.call_tool('get_weather_forecast', args)['result']['status'], 'WEATHER_ERROR')

    def test_schedule_persisted_through_server(self):
        # Giữ dữ liệu test trong thư mục riêng, không xóa dữ liệu.
        db = Path(tempfile.mkdtemp(prefix='coffee-mcp-test-')) / 'tasks.json'
        args = dict(plot_id='CF001', task_type='irrigation_inspection', notes='MCP integration test',
                    scheduled_at=(datetime.now(TIMEZONE) + timedelta(days=1)).isoformat())
        with patch.dict(os.environ, {'FARM_TASKS_FILE': str(db)}):
            reply = self.server.call_tool('schedule_farm_task', args)['result']
            self.assertEqual(reply['status'], 'SUCCESS')
            task = json.loads(db.read_text(encoding='utf-8'))[0]
            row = tuple(task[k] for k in ('task_id', 'plot_id', 'notes'))
            self.assertEqual(row, (reply['task']['task_id'], 'CF001', args['notes']))
            again = self.server.call_tool('schedule_farm_task', args)['result']
            self.assertEqual(again['status'], 'ALREADY_EXISTS')

    def test_invalid_backend_response(self):
        for raw in ['not json', '[]', '{}', '{"status": null}']:
            with self.subTest(raw=raw), patch('mcp_server.dispatch_tool_call', return_value=raw):
                self.assertEqual(self.server.call_tool('get_plot_info', {})['result']['status'], 'EXECUTION_ERROR')
        with patch('mcp_server.dispatch_tool_call', side_effect=RuntimeError('private diagnostic')):
            reply = self.server.call_tool('get_plot_info', {})
            self.assertEqual(reply['result']['status'], 'EXECUTION_ERROR')
            self.assertNotIn('private diagnostic', str(reply))


if __name__ == '__main__':
    unittest.main()
