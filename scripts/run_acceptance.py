"""Nghiệm thu live có giới hạn, giữ bằng chứng riêng mỗi lần chạy.

Chạy: .venv/bin/python scripts/run_acceptance.py
Không tự chấm chất lượng câu trả lời; structural_checks chỉ kiểm tra tool/DB.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from app import load_test_cases, run_react_agent, save_waterfall_trace
from mcp_server import MCPFarmServer
from providers import get_llm_provider, ProviderError
from prompts import CHATBOT_BASELINE_PROMPT
from tools import TIMEZONE
from task_store import load_tasks


def check_case(case_id, trace, db_path):
    executions = [t for t in trace if t['action_type'] == 'TOOL_EXECUTION']
    names = [t['tool_name'] for t in executions]
    checks = {'final_answer': bool(trace) and trace[-1]['action_type'] == 'FINAL_ANSWER',
              'no_runtime_error': not any(t['action_type'] in ('ERROR', 'ITERATION_LIMIT') for t in trace)}
    if case_id == 'TC01':
        checks['no_tools'] = not executions
    elif case_id == 'TC02':
        forecasts = [e for e in executions if e['tool_name'] == 'get_weather_forecast']
        checks['live_forecast'] = any(e['observation'].get('status') == 'SUCCESS'
            and e['observation'].get('data_source') == 'LIVE_API'
            and e['arguments'] == {'latitude': 12.6667, 'longitude': 108.05, 'days': 3}
            for e in forecasts)
    elif case_id == 'TC03':
        saved = [e['observation']['task'] for e in executions
                 if e['tool_name'] == 'schedule_farm_task' and e['observation'].get('status') == 'SUCCESS']
        checks['persisted_in_json'] = False
        if db_path.exists() and len(saved) == 1:
            checks['persisted_in_json'] = saved[0] in load_tasks(db_path)
    elif case_id == 'TC04':
        checks['no_scheduling'] = 'schedule_farm_task' not in names
        checks['plot_then_weather'] = False
        for i, entry in enumerate(executions):
            if entry['tool_name'] == 'get_plot_info' and entry['observation'].get('status') == 'SUCCESS':
                data = entry['observation']['data']
                checks['plot_then_weather'] = any(e['tool_name'] == 'get_weather_forecast'
                    and e['arguments'].get('latitude') == data['latitude']
                    and e['arguments'].get('longitude') == data['longitude']
                    and e['observation'].get('status') == 'SUCCESS'
                    for e in executions[i+1:])
                break
    elif case_id == 'TC05':
        checks['not_found'] = any(e['tool_name'] == 'get_plot_info'
            and e['arguments'].get('plot_id') == 'CF999'
            and e['observation'].get('status') == 'NOT_FOUND' for e in executions)
        checks['no_scheduling'] = 'schedule_farm_task' not in names
    return checks


def main():
    run_dir = ROOT / 'docs/acceptance' / (datetime.now(TIMEZONE).strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
    run_dir.mkdir(parents=True)
    db_path = run_dir / 'farm_tasks.json'
    os.environ['FARM_TASKS_FILE'] = str(db_path)
    summary = {'started_at': datetime.now(TIMEZONE).isoformat(), 'status': 'RUNNING',
               'python': sys.version.split()[0], 'cases': [], 'manual_review_required': True,
               'scope': '5 ca độc lập; chưa thay thế kiểm tra CLI nhiều lượt hoặc đánh giá nội dung cuối.'}

    def write_summary():
        # Mỗi lần ghi một snapshot mới, không thay thế dữ liệu cũ.
        with (run_dir / f'summary-{uuid4().hex[:8]}.json').open('x', encoding='utf-8') as file:
            json.dump(summary, file, ensure_ascii=False, indent=2)

    try:
        provider = get_llm_provider()
        if provider.is_mock:
            raise ProviderError('Nghiệm thu yêu cầu LLM thật qua 9router/Gemini/OpenAI; không chấp nhận Mock.')
        summary.update(provider=type(provider).__name__, model=provider.model_name)
        # Probe một yêu cầu nhỏ, dừng ngay nếu thất bại.
        print('Probe LLM thật...', flush=True)
        probe = provider.generate('Chỉ trả lời: Kết nối thành công.', system_prompt='Trả lời ngắn bằng tiếng Việt.')
        if not probe.strip():
            raise ProviderError('Probe trả phản hồi rỗng.')
        summary['probe'] = probe
        write_summary()
        server = MCPFarmServer()
        for case in load_test_cases():
            print(f"Nghiệm thu {case['id']}...", flush=True)
            allowed_date = (datetime.now(TIMEZONE) + timedelta(days=1)).date()
            confirmations = []

            def approve_test_schedule(args):
                # Chỉ cho phép đúng công việc TC03 trong DB nghiệm thu riêng.
                try:
                    when = datetime.fromisoformat(args['scheduled_at'])
                    permitted = (case['id'] == 'TC03' and args['plot_id'] == 'CF001'
                        and args['task_type'] == 'irrigation_inspection'
                        and when.utcoffset() == timedelta(hours=7) and when.date() == allowed_date
                        and (when.hour, when.minute, when.second) == (7, 0, 0)
                        and args['notes'].strip().casefold().rstrip('.') == 'kiểm tra đầu tưới bị tắc')
                except (KeyError, ValueError, TypeError):
                    permitted = False
                confirmations.append({'arguments': args, 'approved': permitted,
                                      'basis': 'TC03 chỉ ghi DB nghiệm thu, không lịch sản xuất'})
                return permitted

            trace = run_react_agent(case['question'], provider, server,
                confirm_schedule=approve_test_schedule, case_id=case['id'])
            save_waterfall_trace(trace, run_dir / f"{case['id']}-trace.json")
            checks = check_case(case['id'], trace, db_path)
            summary['cases'].append({'id': case['id'], 'structural_checks': checks,
                'structural_pass': all(checks.values()), 'confirmations': confirmations,
                'manual_verdict': 'PENDING', 'expected_behavior': case['expected_behavior']})
            write_summary()
            if any(t['action_type'] == 'ERROR' for t in trace):
                raise ProviderError(f"Dừng sau lỗi LLM tại {case['id']}; không chạy tiếp làm tốn lượt API.")
        # So sánh baseline cho yêu cầu ghi lịch, không có tool.
        summary['baseline'] = provider.generate(load_test_cases()[2]['question'], CHATBOT_BASELINE_PROMPT)
        summary['status'] = 'EXECUTED_REQUIRES_MANUAL_REVIEW'
    except ProviderError as exc:
        summary['status'] = 'BLOCKED'
        summary['reason'] = str(exc)
        print(str(exc), flush=True)
    finally:
        write_summary()
        print(f'Bằng chứng: {run_dir}', flush=True)
    return 0 if summary['status'] == 'EXECUTED_REQUIRES_MANUAL_REVIEW' else 1


if __name__ == '__main__':
    raise SystemExit(main())
