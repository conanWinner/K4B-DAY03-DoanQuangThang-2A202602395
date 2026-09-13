const $ = (selector) => document.querySelector(selector);
const conversation = $('#conversation');
const traceList = $('#trace-list');
const activeTool = $('#active-tool');
const promptEditor = $('#system-prompt');
let sessionId = crypto.randomUUID();
let traceIndex = 0;

function addMessage(role, text) {
  const article = document.createElement('article'); article.className = `message ${role}-message`;
  const body = document.createElement('div'); const label = document.createElement('span');
  label.className = 'message-label'; label.textContent = role === 'user' ? 'BẠN' : 'TRỢ LÝ';
  const paragraph = document.createElement('p'); paragraph.textContent = text; body.append(label, paragraph);
  const avatar = document.createElement('div'); avatar.className = 'avatar'; avatar.setAttribute('aria-hidden', 'true'); avatar.textContent = role === 'user' ? 'BẠN' : 'AI';
  article.append(body, avatar); if (role === 'assistant') article.insertBefore(avatar, body);
  conversation.append(article); conversation.scrollTop = conversation.scrollHeight;
}

function addTrace(kicker, title, detail = '', className = '') {
  if (traceIndex === 0) traceList.replaceChildren(); traceIndex += 1;
  const li = document.createElement('li'); li.className = `trace-item ${className}`;
  const number = document.createElement('span'); number.textContent = String(traceIndex).padStart(2, '0');
  const body = document.createElement('div'); const strong = document.createElement('strong'); strong.textContent = `${kicker} · ${title}`;
  const p = document.createElement('p'); p.textContent = detail; body.append(strong, p); li.append(number, body); traceList.append(li);
  $('#trace-count').textContent = `${traceIndex} bước`;
}

function renderTrace(event) {
  if (event.action_type === 'LLM_STARTED') return addTrace('LLM', `Đang phân tích bước ${event.step}`);
  if (event.action_type === 'TOOL_STARTED') { activeTool.hidden = false; $('#active-tool-name').textContent = event.tool_name; return addTrace('TOOL CALL', event.tool_name, JSON.stringify(event.arguments), 'tool'); }
  if (event.action_type === 'TOOL_EXECUTION') { activeTool.hidden = true; return addTrace('OBSERVATION', event.observation?.status || 'UNKNOWN', `${event.tool_name} · ${event.latency_ms ?? 0} ms`, 'success'); }
  if (event.action_type === 'FINAL_ANSWER') { activeTool.hidden = true; return addTrace('FINAL', 'Đã tạo câu trả lời', `${event.latency_ms ?? 0} ms`, 'success'); }
  if (event.action_type === 'ERROR' || event.action_type === 'ITERATION_LIMIT') { activeTool.hidden = true; addTrace('ERROR', event.output || event.action_type, '', 'tool'); }
}

async function loadConfig() {
  const response = await fetch('/api/config'); const config = await response.json(); const pill = $('#provider-pill');
  pill.classList.toggle('live', config.provider.mode === 'live');
  pill.classList.toggle('error', config.provider.mode === 'error');
  pill.lastElementChild.textContent = `${config.provider.name} · ${config.provider.model}`; pill.title = config.provider.error || '';
  promptEditor.value = config.system_prompt;
  for (const tool of config.tools) { const card = document.createElement('div'); card.className = 'tool-card'; const code = document.createElement('code'); code.textContent = tool.name; const p = document.createElement('p'); p.textContent = tool.description; card.append(code, p); $('#tool-registry').append(card); }
}

promptEditor.addEventListener('input', () => { $('#prompt-state').textContent = 'Đã chỉnh sửa'; });
document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('#message-input').value = button.dataset.prompt; $('#message-input').focus(); }));
$('#new-session').addEventListener('click', () => { sessionId = crypto.randomUUID(); addMessage('assistant', 'Đã bắt đầu phiên mới. Phiên trước vẫn được giữ trong bộ nhớ tới khi máy chủ dừng.'); traceIndex = 0; traceList.innerHTML = '<li class="empty-trace"><span>01</span><p>Phiên mới đang chờ yêu cầu.</p></li>'; $('#trace-count').textContent = '0 bước'; });

$('#chat-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const input = $('#message-input'); const message = input.value.trim(); if (!message) return;
  addMessage('user', message); input.value = ''; const button = $('#send-button'); button.disabled = true; button.firstElementChild.textContent = 'Đang xử lý…';
  try {
    const response = await fetch('/api/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message,session_id:sessionId,system_prompt:promptEditor.value,allow_schedule:$('#allow-schedule').checked}) });
    if (!response.ok) { const error = await response.json(); throw new Error(error.error || `HTTP ${response.status}`); }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
    while (true) { const {value,done} = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), {stream:!done}); const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) { if (!line) continue; const item = JSON.parse(line); if (item.event === 'session') sessionId = item.session_id; if (item.event === 'trace') renderTrace(item.data); if (item.event === 'done') addMessage('assistant', item.answer || 'Đã xử lý xong nhưng chưa có nội dung trả lời.'); if (item.event === 'error') throw new Error(item.message); }
      if (done) break;
    }
  } catch (error) { activeTool.hidden = true; addMessage('assistant', `Không thể hoàn tất: ${error.message}`); }
  finally { button.disabled = false; button.firstElementChild.textContent = 'Gửi yêu cầu'; $('#allow-schedule').checked = false; input.focus(); }
});

loadConfig().catch((error) => addMessage('assistant', `Không tải được cấu hình UI: ${error.message}`));
