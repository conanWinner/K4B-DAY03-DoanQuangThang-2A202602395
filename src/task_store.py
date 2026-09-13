"""Lịch JSON UTF-8 dễ đọc; khóa file trên Linux để tránh ghi đồng thời."""
import fcntl
import json
import os
from pathlib import Path
from uuid import uuid4

FIELDS = {'task_id', 'plot_id', 'task_type', 'scheduled_at', 'notes', 'created_at'}


def load_tasks(path):
    path = Path(path)
    if not path.exists():
        return []
    tasks = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(tasks, list) or any(
        not isinstance(t, dict) or not FIELDS.issubset(t)
        or any(not isinstance(t[k], str) for k in FIELDS) for t in tasks
    ):
        raise ValueError('File lịch không đúng cấu trúc; không ghi đè dữ liệu.')
    return tasks


def save_task(path, task):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tasks = load_tasks(path)
        for existing in tasks:
            if all(existing[k] == task[k] for k in ('plot_id', 'task_type', 'scheduled_at')):
                return {'status': 'ALREADY_EXISTS', 'task_id': existing['task_id'],
                        'message': 'Lịch đã tồn tại; không tạo thêm hoặc thay đổi ghi chú.'}
        tasks.append(task)
        temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        with temporary.open('x', encoding='utf-8') as file:
            json.dump(tasks, file, ensure_ascii=False, indent=2)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        # Thay bản JSON chỉ sau khi toàn bộ dữ liệu cũ và mới đã ghi thành công.
        os.replace(temporary, path)
    return {'status': 'SUCCESS', 'storage': 'LOCAL_JSON', 'task': task,
            'message': 'Đã lưu lịch vào file JSON; chưa thực thi công việc ngoài vườn.'}
