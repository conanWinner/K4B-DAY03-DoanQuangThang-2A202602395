"""Xác nhận một lịch trong lượt chat; không giữ quyền cho lượt sau."""
import re
import unicodedata


def confirms_in_chat(message):
    normalized = unicodedata.normalize('NFD', message.casefold()).replace('đ', 'd')
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r'\s+', ' ', normalized).strip(' .!')
    if re.search(r'\b(khong|chua|dung|huy|khoan|neu)\b', normalized):
        return False
    return bool(re.fullmatch(r'(?:toi |minh |em )?(?:dong y|xac nhan)(?: (?:luu|ghi)(?: lich)?(?: nay)?)?(?: nhe| a)?', normalized)
                or re.match(r'^(?:toi |minh |em )?(?:dong y|xac nhan) (?:luu|ghi) lich\b', normalized))


def schedule_confirmer(message, allowed, history):
    pending = next((e['result'].get('proposed_task') for e in reversed(history)
                    if e.get('role') == 'tool' and e.get('name') == 'schedule_farm_task'), None)
    confirmed = allowed or confirms_in_chat(message)
    accepted = None

    def confirm(arguments):
        nonlocal accepted
        if not confirmed:
            return None  # Chưa xác nhận, không phải từ chối.
        if pending is not None and not allowed and arguments != pending:
            return None  # Lịch thay đổi thì cần xác nhận lại đúng nội dung.
        if accepted is None:
            accepted = dict(arguments)
        return arguments == accepted

    return confirm
