import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from providers import NineRouterProvider, ProviderError, get_llm_provider
from tools import TOOLS_SCHEMA


class NineRouterTests(unittest.TestCase):
    def test_factory_and_config_isolation(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': '9router', 'NINE_ROUTER_BASE_URL': 'http://localhost:20128/v1',
            'NINE_ROUTER_API_KEY': 'test-router-key', 'NINE_ROUTER_MODEL': 'test/model', 'LLM_MODEL': 'ignored'}):
            provider = get_llm_provider()
            try:
                self.assertIsInstance(provider, NineRouterProvider)
                self.assertEqual(provider.model_name, 'test/model')
                self.assertEqual(str(provider.client.base_url), 'http://localhost:20128/v1/')
            finally:
                provider.client.close()

    def test_missing_config_no_direct_provider_fallback(self):
        config = {'NINE_ROUTER_BASE_URL': 'http://localhost:20128/v1',
                  'NINE_ROUTER_API_KEY': 'test-router-key', 'NINE_ROUTER_MODEL': 'test/model'}
        for field in config:
            with self.subTest(field=field), patch.dict(os.environ, {**config, field: '', 'OPENAI_API_KEY': 'unrelated'}):
                with self.assertRaises(ProviderError):
                    NineRouterProvider()
        with self.assertRaises(ProviderError):
            NineRouterProvider(api_key='test', model='test', base_url='https://example.com/v1?key=private')

    def test_real_sdk_serializes_tool_round_trip_to_router(self):
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'router-call-1', 'type': 'function',
                    'function': {'name': 'get_plot_info', 'arguments': '{"plot_id":"CF001"}'}}]}
            else:
                message = {'role': 'assistant', 'content': 'Lô CF001 có dữ liệu mô phỏng.'}
            return httpx.Response(200, json={'id': 'test-response', 'object': 'chat.completion',
                'created': 0, 'model': 'test/model', 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if len(requests) == 1 else 'stop'}]})

        provider = NineRouterProvider(api_key='test-router-key', model='test/model', base_url='http://router.test/v1')
        provider.client.close()
        from openai import OpenAI
        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            provider.client = OpenAI(api_key='test-router-key', base_url='http://router.test/v1',
                                     http_client=http_client, max_retries=0)
            history = [{'role': 'user', 'content': 'Tra cứu CF001'}]
            result = provider.generate_with_tools(history, TOOLS_SCHEMA)
            history.extend([result['assistant'], {'role': 'tool', 'id': 'router-call-1',
                            'result': {'status': 'SUCCESS'}, 'name': 'get_plot_info'}])
            result = provider.generate_with_tools(history, TOOLS_SCHEMA)
            self.assertIn('CF001', result['content'])
        self.assertTrue(all(str(r.url) == 'http://router.test/v1/chat/completions' for r in requests))
        self.assertEqual(requests[0].headers['authorization'], 'Bearer test-router-key')
        payload = json.loads(requests[1].content)
        self.assertEqual(payload['model'], 'test/model')
        self.assertEqual(payload['messages'][-1]['tool_call_id'], 'router-call-1')
        self.assertEqual(json.loads(payload['messages'][-1]['content'])['status'], 'SUCCESS')
        self.assertEqual(len(payload['tools']), 3)


if __name__ == '__main__':
    unittest.main()
