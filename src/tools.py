"""Công cụ chăm sóc cà phê: dữ liệu lô mẫu, thời tiết thật, lịch JSON."""

import json
import math
import os
from task_store import save_task
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

TIMEZONE = ZoneInfo('Asia/Ho_Chi_Minh')
ROOT = Path(__file__).resolve().parents[1]
WEATHER_URL = 'https://api.open-meteo.com/v1/forecast'
TASK_TYPES = ['spraying', 'irrigation', 'fertilizing', 'irrigation_inspection']


def schema(name, description, properties):
    return {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': properties,
        'required': list(properties), 'additionalProperties': False,
    }}


TOOLS_SCHEMA = [
    schema('get_plot_info', 'Tra cứu lô cà phê mô phỏng; lấy tọa độ trước khi hỏi thời tiết của lô.', {
        'plot_id': {'type': 'string', 'minLength': 1, 'description': 'Mã lô, ví dụ CF001.'},
    }),
    schema('get_weather_forecast', 'Lấy dự báo Open-Meteo thật theo giờ, từ hôm nay; không đánh giá an toàn phun thuốc.', {
        'latitude': {'type': 'number', 'minimum': -90, 'maximum': 90},
        'longitude': {'type': 'number', 'minimum': -180, 'maximum': 180},
        'days': {'type': 'integer', 'minimum': 1, 'maximum': 7, 'description': 'Số ngày, gồm hôm nay.'},
    }),
    schema('schedule_farm_task', 'Ghi lịch cục bộ khi người dùng đã yêu cầu/chọn thời điểm rõ ràng. Không tự chọn thuốc hoặc liều; không điều khiển thiết bị.', {
        'plot_id': {'type': 'string', 'minLength': 1},
        'task_type': {'type': 'string', 'enum': TASK_TYPES,
                      'description': 'spraying: phun thuốc; irrigation: tưới; fertilizing: bón phân; irrigation_inspection: kiểm tra hệ thống tưới.'},
        'scheduled_at': {'type': 'string', 'minLength': 1,
                         'description': 'ISO 8601 có múi giờ, ví dụ 2026-09-20T07:00:00+07:00; phải ở tương lai.'},
        'notes': {'type': 'string', 'maxLength': 2000, 'description': 'Ghi chú người dùng cung cấp; để trống nếu không có.'},
    }),
]

# Dữ liệu minh họa, không phải hồ sơ vườn hay đo đạc thực tế.
PLOTS = {
    'CF001': {'name': 'Lô cà phê mẫu 1', 'province': 'Đắk Lắk',
              'latitude': 12.6667, 'longitude': 108.05, 'coffee_type': 'Robusta',
              'growth_stage': 'Nuôi quả (giả định)'},
    'CF002': {'name': 'Lô cà phê mẫu 2', 'province': 'Lâm Đồng',
              'latitude': 11.5753, 'longitude': 107.8053, 'coffee_type': 'Robusta',
              'growth_stage': 'Sau thu hoạch (giả định)'},
}


def get_plot_info(plot_id):
    plot_id = plot_id.strip().upper()
    if plot_id not in PLOTS:
        return {'status': 'NOT_FOUND', 'message': f'Không tìm thấy lô {plot_id}.'}
    return {'status': 'SUCCESS', 'plot_id': plot_id, 'data_source': 'SIMULATED',
            'data': dict(PLOTS[plot_id])}


WEATHER_FIELDS = ['temperature_2m', 'relative_humidity_2m', 'precipitation_probability',
                  'precipitation', 'wind_speed_10m', 'wind_gusts_10m']


def get_weather_forecast(latitude, longitude, days):
    try:
        response = requests.get(WEATHER_URL, params={
            'latitude': latitude, 'longitude': longitude, 'forecast_days': days,
            'hourly': ','.join(WEATHER_FIELDS), 'timezone': 'Asia/Ho_Chi_Minh',
            'wind_speed_unit': 'kmh', 'temperature_unit': 'celsius',
            'precipitation_unit': 'mm',
        }, timeout=(5, 20))
        response.raise_for_status()
        payload = response.json()
        hourly = payload['hourly']
        times = hourly['time']
        units = payload['hourly_units']
        if not isinstance(times, list) or not times:
            raise ValueError('Thiếu thời gian dự báo.')
        for field in WEATHER_FIELDS:
            if (not isinstance(hourly[field], list) or len(hourly[field]) != len(times)
                    or field not in units):
                raise ValueError('Dữ liệu dự báo không đầy đủ.')
        now = datetime.now(TIMEZONE)
        hours = []
        for i, timestamp in enumerate(times):
            forecast_at = datetime.fromisoformat(timestamp).replace(tzinfo=TIMEZONE)
            if forecast_at < now:
                continue
            values = {field: hourly[field][i] for field in WEATHER_FIELDS}
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values.values()):
                continue
            hours.append({'time': forecast_at.isoformat(), **values})
        if not hours:
            raise ValueError('Không có giờ dự báo tương lai với đủ dữ liệu.')
        return {'status': 'SUCCESS', 'source': 'Open-Meteo', 'source_url': WEATHER_URL,
                'data_source': 'LIVE_API', 'retrieved_at': now.isoformat(),
                'model_updated_at': None,
                'note': 'retrieved_at là lúc lấy dữ liệu, không phải lúc mô hình cập nhật. Dự báo có thể thay đổi; không chứng nhận điều kiện phun thuốc.',
                'timezone': 'Asia/Ho_Chi_Minh',
                'requested_location': {'latitude': latitude, 'longitude': longitude},
                'units': units, 'hourly': hours}
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        return {'status': 'WEATHER_ERROR',
                'message': 'Không lấy được dự báo hợp lệ từ Open-Meteo. Hãy thử lại; chưa có dữ liệu để đề xuất lịch theo thời tiết.'}


def schedule_farm_task(plot_id, task_type, scheduled_at, notes):
    plot = get_plot_info(plot_id)
    if plot['status'] != 'SUCCESS':
        return plot
    try:
        when = datetime.fromisoformat(scheduled_at)
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError('Thời gian phải có múi giờ.')
        when = when.astimezone(TIMEZONE)
        if when <= datetime.now(TIMEZONE):
            raise ValueError('Thời gian phải ở tương lai.')
    except ValueError as exc:
        return {'status': 'INVALID_ARGUMENTS', 'message': str(exc)}
    db_path = Path(os.environ.get('FARM_TASKS_FILE', str(ROOT / 'data' / 'farm_tasks.json')))
    task = {'task_id': str(uuid4()), 'plot_id': plot['plot_id'], 'task_type': task_type,
            'scheduled_at': when.isoformat(), 'notes': notes,
            'created_at': datetime.now(TIMEZONE).isoformat()}
    try:
        return save_task(db_path, task)
    except (OSError, ValueError):
        return {'status': 'STORAGE_ERROR', 'message': 'Không thể lưu lịch; chưa xác nhận thành công.'}


TOOL_ROUTER = {'get_plot_info': get_plot_info, 'get_weather_forecast': get_weather_forecast,
               'schedule_farm_task': schedule_farm_task}


def validate_arguments(tool_name, arguments):
    """Kiểm tra tập con JSON Schema dùng bởi ba tool trước khi thực thi."""
    spec = next(t['parameters'] for t in TOOLS_SCHEMA if t['name'] == tool_name)
    if not isinstance(arguments, dict) or set(arguments) != set(spec['required']):
        raise ValueError('Phải cung cấp đúng các tham số: ' + ', '.join(spec['required']))
    for key, rule in spec['properties'].items():
        value = arguments[key]
        kind = rule['type']
        valid = ((kind == 'string' and isinstance(value, str))
                 or (kind == 'integer' and type(value) is int)
                 or (kind == 'number' and type(value) in (int, float) and math.isfinite(value)))
        if not valid:
            raise ValueError(f'{key}: sai kiểu dữ liệu.')
        if kind == 'string':
            if len(value.strip()) < rule.get('minLength', 0) or len(value) > rule.get('maxLength', 10000):
                raise ValueError(f'{key}: độ dài không hợp lệ.')
        elif not rule.get('minimum', -math.inf) <= value <= rule.get('maximum', math.inf):
            raise ValueError(f'{key}: ngoài khoảng cho phép.')
        if 'enum' in rule and value not in rule['enum']:
            raise ValueError(f'{key}: giá trị không được hỗ trợ.')


def dispatch_tool_call(tool_name, arguments):
    """Giữ giao diện chuỗi JSON của starter để Task 2.1 tích hợp MCP."""
    if not isinstance(tool_name, str) or tool_name not in TOOL_ROUTER:
        result = {'status': 'UNKNOWN_TOOL', 'message': 'Công cụ không tồn tại.'}
    else:
        try:
            validate_arguments(tool_name, arguments)
            result = TOOL_ROUTER[tool_name](**arguments)
        except (ValueError, TypeError) as exc:
            result = {'status': 'INVALID_ARGUMENTS', 'message': str(exc)}
    return json.dumps(result, ensure_ascii=False, allow_nan=False)
