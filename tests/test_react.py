import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import run_react_agent, save_waterfall_trace
from mcp_server import MCPFarmServer
from providers import ProviderError, GeminiProvider, OpenAIProvider, get_llm_provider
from tools import TIMEZONE


def answer(text):
    return {'content': text, 'calls': [], 'assistant': {'role': 'assistant', 'content': text}}


def action(name, args, call_id='call-1'):
    return {'content': '', 'calls': [{'id': call_id, 'name': name, 'arguments': args}],
            'assistant': {'role': 'assistant', 'content': ''}}


class ScriptedProvider:
    is_mock = True
    model_name = 'scripted-test'

    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []

    def generate_with_tools(self, history, tools_schema, system_prompt=''):
        self.seen.append(list(history))
        reply = next(self.responses)
        if isinstance(reply, Exception):
            raise reply
        return reply


class ReActTests(unittest.TestCase):
    def run_agent(self, provider, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_react_agent('Tra cứu CF001, xem thời tiết; chưa tạo lịch.', provider, MCPFarmServer(), **kwargs)

    def test_multistep_observation_and_followup(self):
        provider = ScriptedProvider([
            action('get_plot_info', {'plot_id': 'CF001'}),
            action('get_weather_forecast', {'latitude': 12.6667, 'longitude': 108.05, 'days': 3}),
            answer('Chưa tạo lịch; cần sản phẩm và thời điểm bạn chọn.'),
            answer('Tôi còn nhớ lô CF001.')])
        history = []
        with patch('tools.get_weather_forecast'):
            # Router giữ tham chiếu riêng: thay tại đúng ranh giới công cụ.
            with patch.dict('tools.TOOL_ROUTER', {'get_weather_forecast': lambda **kw: {'status': 'SUCCESS', 'data_source': 'TEST_FIXTURE'}}):
                trace = self.run_agent(provider, history=history)
        self.assertEqual([e['tool_name'] for e in trace if e['action_type'] == 'TOOL_EXECUTION'],
                         ['get_plot_info', 'get_weather_forecast'])
        self.assertEqual(provider.seen[1][-1]['result']['plot_id'], 'CF001')
        self.assertEqual(provider.seen[2][-1]['result']['data_source'], 'TEST_FIXTURE')
        self.run_agent(provider, history=history)
        self.assertTrue(any(e.get('content') == 'Chưa tạo lịch; cần sản phẩm và thời điểm bạn chọn.' for e in provider.seen[3]))
        self.assertTrue(all(e['latency_ms'] >= 0 and e['mode'] == 'MOCK' for e in trace))

    def test_schedule_requires_approval_then_persists(self):
        args = dict(plot_id='CF001', task_type='irrigation_inspection',
                    scheduled_at=(datetime.now(TIMEZONE) + timedelta(days=1)).isoformat(), notes='Test')
        db = Path(tempfile.mkdtemp(prefix='coffee-react-test-')) / 'tasks.json'
        with patch.dict(os.environ, {'FARM_TASKS_FILE': str(db)}):
            for callback, status in [(None, 'CONFIRMATION_REQUIRED'), (lambda a: False, 'CANCELLED')]:
                provider = ScriptedProvider([action('schedule_farm_task', args), answer('Chưa lưu.')])
                trace = self.run_agent(provider, confirm_schedule=callback)
                self.assertEqual(trace[1]['observation']['status'], status)
                self.assertFalse(db.exists())
            provider = ScriptedProvider([action('schedule_farm_task', args), answer('Đã lưu.')])
            trace = self.run_agent(provider, confirm_schedule=lambda proposed: proposed == args)
            self.assertEqual(trace[1]['observation']['status'], 'SUCCESS')
            self.assertEqual(len(json.loads(db.read_text(encoding='utf-8'))), 1)

    def test_errors_and_iteration_limit(self):
        provider = ScriptedProvider([ProviderError('API timeout')])
        self.assertEqual(self.run_agent(provider)[-1]['action_type'], 'ERROR')
        provider = ScriptedProvider([action('get_plot_info', {'plot_id': 'CF999'})] * 2)
        trace = self.run_agent(provider, max_iterations=2)
        self.assertEqual(trace[1]['observation']['status'], 'NOT_FOUND')
        self.assertEqual(trace[-1]['action_type'], 'ITERATION_LIMIT')
        self.assertEqual(self.run_agent(ScriptedProvider([answer('')]))[-1]['action_type'], 'ERROR')

    def test_multiple_calls_all_receive_results(self):
        reply = action('get_plot_info', {'plot_id': 'CF001'}, 'a')
        reply['calls'].extend(action('get_plot_info', {'plot_id': 'CF002'}, 'b')['calls'])
        p = ScriptedProvider([reply, answer('Hai lô.')])
        self.run_agent(p)
        self.assertEqual([e['id'] for e in p.seen[1] if e['role'] == 'tool'], ['a', 'b'])

    def test_trace_never_overwrites(self):
        path = Path(tempfile.mkdtemp(prefix='coffee-trace-test-')) / 'trace.json'
        with contextlib.redirect_stdout(io.StringIO()):
            save_waterfall_trace([{'old': True}], path)
            with self.assertRaises(FileExistsError):
                save_waterfall_trace([], path)
        self.assertEqual(json.loads(path.read_text()), [{'old': True}])


class AdapterTests(unittest.TestCase):
    def test_openai_tool_id_and_native_history(self):
        from openai.types.chat import ChatCompletionMessage
        p = OpenAIProvider.__new__(OpenAIProvider)
        p.model_name, p.client = 'test', MagicMock()
        msg = ChatCompletionMessage(role='assistant', tool_calls=[{
            'id': 'native-id', 'type': 'function',
            'function': {'name': 'get_plot_info', 'arguments': '{"plot_id":"CF001"}'}}])
        p.client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        history = [{'role': 'user', 'content': 'Tra cứu'}]
        r = p.generate_with_tools(history, [])
        history.extend([r['assistant'], {'role': 'tool', 'id': 'native-id', 'name': 'get_plot_info', 'result': {'status': 'SUCCESS'}}])
        p.generate_with_tools(history, [])
        messages = p.client.chat.completions.create.call_args.kwargs['messages']
        self.assertEqual(messages[-1]['tool_call_id'], 'native-id')
        self.assertEqual(messages[-2]['tool_calls'][0]['id'], 'native-id')
        p.client.chat.completions.create.side_effect = TimeoutError
        with self.assertRaises(ProviderError):
            p.generate_with_tools(history, [])

    def test_gemini_preserves_signature_and_function_response(self):
        from google.genai import types
        p = GeminiProvider.__new__(GeminiProvider)
        p.model_name, p.client = 'test', MagicMock()
        content = types.Content(role='model', parts=[types.Part(
            thought_signature=b'opaque-signature', function_call=types.FunctionCall(
                id='native-id', name='get_plot_info', args={'plot_id': 'CF001'}))])
        p.client.models.generate_content.return_value = SimpleNamespace(candidates=[SimpleNamespace(content=content)])
        history = [{'role': 'user', 'content': 'Tra cứu'}]
        from tools import TOOLS_SCHEMA
        r = p.generate_with_tools(history, TOOLS_SCHEMA)
        history.extend([r['assistant'], {'role': 'tool', 'id': 'native-id', 'native_id': 'native-id',
                                        'name': 'get_plot_info', 'result': {'status': 'SUCCESS'}}])
        p.generate_with_tools(history, TOOLS_SCHEMA)
        contents = p.client.models.generate_content.call_args.kwargs['contents']
        self.assertEqual(contents[-2].parts[0].thought_signature, b'opaque-signature')
        self.assertEqual(contents[-1].parts[0].function_response.id, 'native-id')
        self.assertEqual(contents[-1].parts[0].function_response.response['status'], 'SUCCESS')
        p.client.models.generate_content.side_effect = TimeoutError
        with self.assertRaises(ProviderError):
            p.generate_with_tools(history, TOOLS_SCHEMA)

    def test_missing_key_never_falls_back(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'gemini', 'GEMINI_API_KEY': ''}):
            with self.assertRaises(ProviderError):
                get_llm_provider()


if __name__ == '__main__':
    unittest.main()
