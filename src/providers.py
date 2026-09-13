"""Native tool calling với lịch sử hội thoại; không fallback khi API lỗi."""
import json
import os
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()


class ProviderError(RuntimeError):
    pass


class BaseLLMProvider:
    is_mock = False

    def generate(self, prompt, system_prompt=''):
        return self.generate_with_tools([{'role': 'user', 'content': prompt}], [], system_prompt)['content']


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key=None, model=None):
        from openai import OpenAI
        key = api_key or os.getenv('OPENAI_API_KEY')
        if not key or key.startswith('your_'):
            raise ProviderError('Chưa cấu hình OPENAI_API_KEY.')
        self.model_name = model or os.getenv('LLM_MODEL') or 'gpt-4o-mini'
        self.client = OpenAI(api_key=key, timeout=30, max_retries=0)

    def generate_with_tools(self, history, tools_schema, system_prompt=''):
        messages = [{'role': 'system', 'content': system_prompt}]
        for entry in history:
            if entry['role'] == 'assistant':
                messages.append(entry['openai'] if 'openai' in entry else {
                    'role': 'assistant', 'content': entry.get('content', '')})
            elif entry['role'] == 'tool':
                messages.append({'role': 'tool', 'tool_call_id': entry['id'],
                                 'content': json.dumps(entry['result'], ensure_ascii=False)})
            else:
                messages.append({'role': 'user', 'content': entry['content']})
        try:
            kwargs = dict(model=self.model_name, messages=messages)
            if tools_schema:
                kwargs.update(tools=[{'type': 'function', 'function': t} for t in tools_schema],
                              parallel_tool_calls=False)
            msg = self.client.chat.completions.create(**kwargs).choices[0].message
            calls = [{'id': c.id, 'name': c.function.name, 'arguments': json.loads(c.function.arguments)}
                     for c in msg.tool_calls or []]
            return {'content': msg.content or '', 'calls': calls,
                    'assistant': {'role': 'assistant', 'content': msg.content or '',
                                  'openai': msg.model_dump(exclude_none=True)}}
        except Exception as exc:
            raise ProviderError(f'{type(self).__name__} thất bại ({type(exc).__name__}); không chuyển sang Mock.') from None


class NineRouterProvider(OpenAIProvider):
    """9router dùng Chat Completions tương thích OpenAI, key riêng của router."""
    def __init__(self, api_key=None, model=None, base_url=None):
        from openai import OpenAI
        from urllib.parse import urlsplit
        key = api_key or os.getenv('NINE_ROUTER_API_KEY', '')
        endpoint = (base_url or os.getenv('NINE_ROUTER_BASE_URL', '')).strip().rstrip('/')
        selected_model = (model or os.getenv('NINE_ROUTER_MODEL', '')).strip()
        if not endpoint:
            raise ProviderError('Chưa cấu hình NINE_ROUTER_BASE_URL (URL API kết thúc bằng /v1).')
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.path.endswith('/v1')):
            raise ProviderError('NINE_ROUTER_BASE_URL phải là URL http(s) kết thúc bằng /v1, không chứa key/query.')
        if not selected_model or selected_model.startswith('your_'):
            raise ProviderError('Chưa cấu hình NINE_ROUTER_MODEL: dùng đúng ID model/combo trên 9router.')
        if not key or key.startswith('your_'):
            raise ProviderError('Chưa cấu hình NINE_ROUTER_API_KEY: dùng key do 9router cấp.')
        self.model_name = selected_model
        self.client = OpenAI(api_key=key, base_url=endpoint, timeout=30, max_retries=0)


class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key=None, model=None):
        from google import genai
        from google.genai import types
        key = api_key or os.getenv('GEMINI_API_KEY')
        if not key or key.startswith('your_'):
            raise ProviderError('Chưa cấu hình GEMINI_API_KEY.')
        self.model_name = model or os.getenv('LLM_MODEL') or 'gemini-2.5-flash'
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=30000, retry_options=types.HttpRetryOptions(attempts=1)))

    def generate_with_tools(self, history, tools_schema, system_prompt=''):
        from google.genai import types
        contents = []
        for entry in history:
            if 'gemini' in entry:
                # Giữ nguyên Content, bao gồm thought_signature của provider.
                contents.append(entry['gemini'])
            elif entry['role'] == 'tool':
                part = types.Part(function_response=types.FunctionResponse(
                    name=entry['name'], id=entry.get('native_id'), response=entry['result']))
                if contents and contents[-1].role == 'user' and contents[-1].parts[0].function_response:
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role='user', parts=[part]))
            else:
                contents.append(types.Content(role='model' if entry['role'] == 'assistant' else 'user',
                                              parts=[types.Part(text=entry.get('content', ''))]))
        try:
            declarations = [types.FunctionDeclaration(name=t['name'], description=t['description'],
                            parameters_json_schema=t['parameters']) for t in tools_schema]
            config = types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.2,
                tools=[types.Tool(function_declarations=declarations)] if declarations else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
            response = self.client.models.generate_content(model=self.model_name, contents=contents, config=config)
            content = response.candidates[0].content
            calls, texts = [], []
            for part in content.parts or []:
                if part.function_call:
                    c = part.function_call
                    calls.append({'id': c.id or str(uuid4()), 'native_id': c.id,
                                  'name': c.name, 'arguments': dict(c.args or {})})
                elif part.text and not part.thought:
                    texts.append(part.text)
            text = '\n'.join(texts)
            return {'content': text, 'calls': calls,
                    'assistant': {'role': 'assistant', 'content': text, 'gemini': content}}
        except Exception as exc:
            raise ProviderError(f'Gemini thất bại ({type(exc).__name__}); không chuyển sang Mock.') from None


class MockOfflineProvider(BaseLLMProvider):
    """Demo hạn chế, không mô phỏng thời tiết thật hay tự ghi lịch."""
    is_mock = True
    model_name = 'offline-coffee-demo'

    def generate_with_tools(self, history, tools_schema, system_prompt=''):
        import re
        query = next(e['content'] for e in reversed(history) if e['role'] == 'user')
        if history[-1]['role'] == 'tool':
            text = '[MOCK] Kết quả công cụ: ' + json.dumps(history[-1]['result'], ensure_ascii=False)
            calls = []
        else:
            match = re.search(r'CF\d+', query, re.I)
            calls = ([{'id': str(uuid4()), 'name': 'get_plot_info', 'arguments': {'plot_id': match[0]}}]
                     if match and tools_schema else [])
            text = '' if calls else '[MOCK] Tôi hỗ trợ tra cứu lô, xem dự báo và ghi lịch. Demo offline chỉ hỗ trợ tra cứu lô; dùng provider thật để hội thoại đầy đủ.'
        return {'content': text, 'calls': calls, 'assistant': {'role': 'assistant', 'content': text}}


def get_llm_provider():
    kind = os.getenv('LLM_PROVIDER', 'mock').lower()
    factory = {'gemini': GeminiProvider, 'openai': OpenAIProvider, 'mock': MockOfflineProvider, '9router': NineRouterProvider}
    if kind not in factory:
        raise ProviderError('LLM_PROVIDER phải là 9router, gemini, openai hoặc mock.')
    return factory[kind]()
