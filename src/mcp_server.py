"""MCP mô phỏng trong tiến trình theo giao diện CODELAB.

Đóng gói kết quả tool trong envelope của starter; chưa triển khai transport,
handshake hay đầy đủ giao thức MCP/JSON-RPC. Giữ `result` cho client hiện tại.
"""

import json
import sys
from copy import deepcopy
from typing import Any, Dict, List

from tools import TOOLS_SCHEMA, dispatch_tool_call

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


class MCPFarmServer:
    """Cầu nối giữa Agent và các công cụ chăm sóc cà phê trong bản lab."""

    def __init__(self, server_name: str = 'coffee-farm-mcp-server'):
        self.server_name = server_name
        self.version = '2026.1.0'

    def list_tools(self) -> List[Dict[str, Any]]:
        """Cung cấp schema cho provider mà không cho sửa registry gốc."""
        return deepcopy(TOOLS_SCHEMA)

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch, đọc JSON và giữ nguyên trạng thái nghiệp vụ của tool.

        Lỗi thực thi bất ngờ được chuyển thành Observation lỗi để Agent không
        báo thành công. Không đưa chi tiết ngoại lệ nội bộ vào phản hồi cho LLM.
        """
        try:
            content = json.loads(dispatch_tool_call(tool_name, arguments))
            if not isinstance(content, dict) or not isinstance(content.get('status'), str):
                raise ValueError('Tool result must contain a status.')
        except Exception:
            content = {
                'status': 'EXECUTION_ERROR',
                'message': 'Công cụ không trả về kết quả hợp lệ; chưa thể xác nhận thao tác thành công.',
            }
        return {
            'jsonrpc': '2.0',
            'server': self.server_name,
            'tool': tool_name,
            'result': content,
        }


# Tương thích app.py của starter đến khi chuyển Agent sang nông nghiệp ở Task 2.2.
MCPAcademicServer = MCPFarmServer


if __name__ == '__main__':
    server = MCPFarmServer()
    print(f'✅ [MCP SERVER] Đã khởi tạo {server.server_name} (Version: {server.version})')
    print('ℹ️ Chế độ mô phỏng trong tiến trình theo CODELAB.')
    print(f'📦 Số lượng Tools công bố: {len(server.list_tools())}')
    for tool in server.list_tools():
        print(f"  - {tool['name']}")
    response = server.call_tool('get_plot_info', {'plot_id': 'CF001'})
    if response['result']['status'] != 'SUCCESS':
        raise SystemExit('❌ Kiểm tra tra cứu lô thất bại.')
    print('✅ [TASK 2.1] Tra cứu CF001 qua dispatcher thành công:')
    print(json.dumps(response, ensure_ascii=False, indent=2))
