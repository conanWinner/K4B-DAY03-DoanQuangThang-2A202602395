"""ReAct nhiều bước cho trợ lý cà phê; trace riêng cho từng lần chạy."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from uuid import uuid4

from mcp_server import MCPFarmServer
from prompts import CHATBOT_BASELINE_PROMPT, REACT_AGENT_SYSTEM_PROMPT, MAX_ITERATIONS
from providers import get_llm_provider, ProviderError
from tools import TIMEZONE, validate_arguments

ROOT = Path(__file__).resolve().parents[1]


def load_test_cases():
    with (ROOT / 'config/test_cases.json').open(encoding='utf-8') as file:
        return json.load(file)


def save_waterfall_trace(trace_data, path=None):
    # Không ghi đè trace cũ: mỗi lần lưu tạo file mới, kể cả khi truyền --trace.
    target = Path(path) if path else ROOT / 'docs/traces' / f'trace-{uuid4()}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as file:
        json.dump(trace_data, file, ensure_ascii=False, indent=2)
    print(f'Trace: {target}')
    return target


def run_baseline_chatbot(user_query, provider):
    answer = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    print(f'Chatbot: {answer}')
    return answer


def run_react_agent(user_query, provider, mcp_server, history=None, confirm_schedule=None,
                    max_iterations=MAX_ITERATIONS, case_id=None, system_prompt=None,
                    on_event=None):
    """history thuộc một phiên; mỗi tool call luôn có Observation tương ứng.

    confirm_schedule nhận tham số lịch cụ thể, trả True nếu người dùng đồng ý.
    Mặc định không ghi lịch. Test có thể truyền callback cho phép trên DB riêng.
    """
    history = history if history is not None else []
    history.append({'role': 'user', 'content': user_query})
    trace = []
    run_id = str(uuid4())
    prompt = (system_prompt or REACT_AGENT_SYSTEM_PROMPT) + (
        '\nThời gian hiện tại: ' + datetime.now(TIMEZONE).isoformat())
    metadata = {'run_id': run_id, 'case_id': case_id, 'query': user_query,
                'provider': type(provider).__name__, 'model': provider.model_name,
                'mode': 'MOCK' if provider.is_mock else 'LIVE_API'}

    def event(step, kind, started, **data):
        record = {**metadata, 'step': step, 'action_type': kind,
                  'timestamp': datetime.now(TIMEZONE).isoformat(),
                  'latency_ms': round((time.perf_counter() - started) * 1000, 3), **data}
        trace.append(record)
        if on_event:
            on_event(record)

    for step in range(1, max_iterations + 1):
        started = time.perf_counter()
        print(f'Bước {step}/{max_iterations}: đang gọi {type(provider).__name__}...')
        if on_event:
            on_event({**metadata, 'step': step, 'action_type': 'LLM_STARTED',
                      'timestamp': datetime.now(TIMEZONE).isoformat()})
        try:
            reply = provider.generate_with_tools(history, mcp_server.list_tools(), system_prompt=prompt)
            calls = reply['calls']
            if not isinstance(calls, list) or len(calls) > 8:
                raise ProviderError('Danh sách tool call không hợp lệ hoặc vượt giới hạn 8.')
            ids = []
            for call in calls:
                if not isinstance(call, dict) or not isinstance(call.get('id'), str) or not isinstance(call.get('name'), str):
                    raise ProviderError('Tool call không hợp lệ.')
                ids.append(call['id'])
            if len(ids) != len(set(ids)):
                raise ProviderError('Tool call ID bị trùng.')
            if not calls and not reply.get('content', '').strip():
                raise ProviderError('LLM trả phản hồi rỗng.')
        except Exception as exc:
            message = str(exc) if isinstance(exc, ProviderError) else f'Lỗi phản hồi LLM ({type(exc).__name__}).'
            event(step, 'ERROR', started, output=message)
            history.append({'role': 'assistant', 'content': message})
            print(message)
            return trace
        history.append(reply['assistant'])
        if not calls:
            event(step, 'FINAL_ANSWER', started, thought='LLM trả lời từ ngữ cảnh và kết quả công cụ.',
                  output=reply['content'])
            print('Trợ lý:', reply['content'])
            return trace
        event(step, 'LLM_TOOL_CALLS', started,
              thought='LLM đề xuất gọi công cụ; đây là tóm tắt hành động, không phải suy luận nội bộ.',
              calls=[{k: c.get(k) for k in ('id', 'name', 'arguments')} for c in calls])
        for call in calls:
            tool_start = time.perf_counter()
            name, args = call['name'], call.get('arguments', {})
            if on_event:
                on_event({**metadata, 'step': step, 'action_type': 'TOOL_STARTED',
                          'timestamp': datetime.now(TIMEZONE).isoformat(),
                          'tool_call_id': call['id'], 'tool_name': name,
                          'arguments': args})
            observation = None
            if name == 'schedule_farm_task':
                try:
                    validate_arguments(name, args)
                except (ValueError, TypeError) as exc:
                    observation = {'status': 'INVALID_ARGUMENTS', 'message': str(exc)}
                if observation is None:
                    decision = confirm_schedule(dict(args)) if confirm_schedule else None
                    if decision is None:
                        observation = {'status': 'CONFIRMATION_REQUIRED', 'proposed_task': args,
                                       'message': 'Chưa lưu lịch. Hãy xác nhận lịch trên bằng câu “Tôi đồng ý lưu lịch” hoặc bật quyền ghi lịch trong giao diện.'}
                    elif not decision:
                        observation = {'status': 'CANCELLED', 'message': 'Người dùng chưa đồng ý, không lưu lịch.'}
            if observation is None:
                observation = mcp_server.call_tool(name, args)['result']
            history.append({'role': 'tool', 'id': call['id'], 'native_id': call.get('native_id'),
                            'name': name, 'result': observation})
            event(step, 'TOOL_EXECUTION', tool_start, tool_call_id=call['id'], tool_name=name,
                  arguments=args, observation=observation)
            print(f"  {name}: {observation.get('status')}")
    started = time.perf_counter()
    message = 'Đã đạt giới hạn vòng lặp; yêu cầu chưa hoàn tất. Xem trace để biết công việc nào đã được ghi nhận.'
    event(max_iterations, 'ITERATION_LIMIT', started, output=message)
    history.append({'role': 'assistant', 'content': message})
    print(message)
    return trace


def confirm_in_cli(arguments):
    print('Lịch đề xuất:', json.dumps(arguments, ensure_ascii=False, indent=2))
    try:
        return input('Lưu lịch này? Gõ yes để lưu: ').strip().lower() == 'yes'
    except (EOFError, KeyboardInterrupt):
        return False


def main():
    parser = argparse.ArgumentParser(description='Trợ lý chăm sóc cà phê')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--interactive', action='store_true')
    mode.add_argument('--all', action='store_true')
    parser.add_argument('--baseline', action='store_true', help='So sánh chatbot với cùng câu hỏi')
    parser.add_argument('--confirm-schedules', action='store_true',
                        help='Hỏi xác nhận lịch cụ thể trong chế độ --all')
    parser.add_argument('--trace', help='File trace mới; không được tồn tại trước')
    args = parser.parse_args()
    if args.trace and Path(args.trace).exists():
        parser.error('File trace đã tồn tại. Chọn tên mới để giữ dữ liệu cũ.')
    try:
        provider = get_llm_provider()
    except ProviderError as exc:
        print(exc)
        return 1
    print(f'Provider: {type(provider).__name__} | Model: {provider.model_name}')
    server, history, traces = MCPFarmServer(), [], []
    try:
        if args.interactive:
            print('Nhập câu hỏi; exit/quit để thoát. Lịch sử giữ trong phiên này.')
            while True:
                query = input('Bạn: ').strip()
                if query.lower() in ('exit', 'quit'):
                    break
                if not query:
                    continue
                if args.baseline:
                    run_baseline_chatbot(query, provider)
                traces.extend(run_react_agent(query, provider, server, history, confirm_in_cli))
        else:
            cases = load_test_cases() if args.all else [load_test_cases()[0]]
            for case in cases:
                print(f"\n{case['id']}: {case['question']}")
                if args.baseline:
                    run_baseline_chatbot(case['question'], provider)
                traces.extend(run_react_agent(case['question'], provider, server, case_id=case['id'],
                    confirm_schedule=confirm_in_cli if args.confirm_schedules else None))
            print('Đã thực thi; chưa tự chấm đạt. Chế độ --all không ghi lịch nếu chưa có xác nhận.')
    except (EOFError, KeyboardInterrupt):
        print('\nĐã dừng phiên.')
    except ProviderError as exc:
        print(exc)
        return 1
    finally:
        if traces:
            save_waterfall_trace(traces, args.trace)
    return int(any(t['action_type'] in ('ERROR', 'ITERATION_LIMIT') for t in traces))


if __name__ == '__main__':
    raise SystemExit(main())
