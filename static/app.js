const $ = id => document.getElementById(id);
let activeId = null, currentImage = null, busy = false, recognition = null, listening = false;
let view = 'home';
const toast = message => { const el = $('toast'); el.textContent = message; el.classList.remove('hidden'); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.add('hidden'), 5000); };
const api = async (url, options) => { const response = await fetch(url, options); let data; try { data = await response.json(); } catch { throw Error('Máy chủ không trả về JSON. Kiểm tra Flask đang chạy.'); } if (!response.ok) throw Error(data.error || `Lỗi HTTP ${response.status}`); return data; };
function nav(page) {
  view = page;
  $('homeScreen').classList.toggle('hidden', page !== 'home');
  $('historyScreen').classList.toggle('hidden', page !== 'history');
  $('chatScreen').classList.toggle('hidden', page !== 'chat');
  $('homeNav').classList.toggle('active', page === 'home');
  $('historyNav').classList.toggle('active', page === 'history');
  const titles = {home:'Trang chủ', history:'Lịch sử trò chuyện', chat:'Cuộc trò chuyện'};
  $('breadcrumb').textContent = 'Nam Smart / ' + titles[page];
  $('sidebar').classList.remove('open'); $('overlay').classList.remove('open');
  if (page === 'history') loadHistory();
}
function newChat() { activeId = null; $('messageContainer').replaceChildren(); clearImage(); $('userInput').value = ''; nav('home'); }
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// Protect math expressions before Markdown processing: Markdown otherwise removes LaTeX backslashes.
function renderMarkdown(source) {
  let input = String(source || '');
  // Also accept common unwrapped textbook expressions like (2x = 1 \\Rightarrow x = \\dfrac{1}{2}).
  input = input.replace(/\(([^\n]*?\\(?:Rightarrow|Leftrightarrow|dfrac|frac|sqrt)[^\n]*?)\)/g, (match, math) => `\\(${math}\\)`);
  const math = [];
  const tokenized = input.replace(/(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\$)[^\n$]+\$)/g, expr => {
    const token = `NAMSMARTMATHTOKEN${math.length}END`;
    math.push(expr);
    return token;
  });
  const html = window.marked ? marked.parse(tokenized, {breaks:true, gfm:true}) : escapeHtml(tokenized).replace(/\n/g,'<br>');
  // Sanitize before restoring math. Escaped math is text, never executable HTML.
  const safe = window.DOMPurify ? DOMPurify.sanitize(html) : escapeHtml(input).replace(/\n/g,'<br>');
  if (!window.DOMPurify) return safe;
  return safe.replace(/NAMSMARTMATHTOKEN(\d+)END/g, (_, index) => escapeHtml(math[Number(index)] || ''));
}
async function typeset(node) {
  if (!window.MathJax) return;
  try { if (MathJax.startup?.promise) await MathJax.startup.promise; if (MathJax.typesetPromise) await MathJax.typesetPromise([node]); } catch (error) { console.warn('MathJax:', error); }
}
function addMessage(text, role, image) {
  nav('chat');
  const row = document.createElement('div'); row.className = 'message-row ' + (role === 'user' ? 'user' : 'assistant');
  if (role !== 'user') { const avatar = document.createElement('div'); avatar.className='message-avatar'; avatar.innerHTML='<i class="fa-solid fa-robot"></i>'; row.appendChild(avatar); }
  const bubble = document.createElement('div'); bubble.className = 'message-bubble';
  if (image) { const img = document.createElement('img'); img.className='uploaded'; img.src=image; img.alt='Ảnh bài tập'; bubble.appendChild(img); }
  if (role === 'user') { const label = document.createElement('div'); label.textContent=text || '📷 Hãy đọc và giải bài trong ảnh này.'; bubble.appendChild(label); }
  else {
    const content = document.createElement('div'); content.innerHTML = renderMarkdown(text); bubble.appendChild(content);
    const speak = document.createElement('button'); speak.className='speak-button'; speak.innerHTML='<i class="fa-solid fa-volume-high"></i> Nghe đọc';
    speak.addEventListener('click', () => speakText(text)); bubble.appendChild(speak);
    typeset(content);
  }
  row.appendChild(bubble); $('messageContainer').appendChild(row);
  requestAnimationFrame(() => { $('content').scrollTop = $('content').scrollHeight; });
  return row;
}
async function loadHistory() {
  try {
    const list = await api('/api/conversations');
    $('historyList').replaceChildren(); $('historyGrid').replaceChildren();
    if (!list.length) { $('historyList').innerHTML='<p class="muted-history">Chưa có cuộc trò chuyện nào.</p>'; $('historyGrid').innerHTML='<div class="empty-state"><i class="fa-regular fa-comment-dots"></i><h3>Chưa có cuộc trò chuyện</h3><p>Hãy bắt đầu bằng một câu hỏi mới nhé!</p></div>'; return; }
    for (const item of list) {
      const row = document.createElement('div'); row.className='history-entry';
      row.innerHTML='<i class="fa-regular fa-message"></i><span class="entry-title"></span><button title="Xóa cuộc trò chuyện" aria-label="Xóa"><i class="fa-solid fa-trash"></i></button>';
      row.querySelector('.entry-title').textContent = item.title;
      row.addEventListener('click', () => openConversation(item.id));
      row.querySelector('button').addEventListener('click', e => { e.stopPropagation(); deleteConversation(item.id); });
      $('historyList').appendChild(row);
      const card = document.createElement('div'); card.className='history-card';
      card.innerHTML='<span class="card-icon"><i class="fa-regular fa-message"></i></span><div class="card-info"><strong></strong><small></small></div><button title="Xóa" aria-label="Xóa cuộc trò chuyện"><i class="fa-solid fa-trash"></i></button>';
      card.querySelector('strong').textContent=item.title;
      card.querySelector('small').textContent=new Date(item.updated_at).toLocaleString('vi-VN');
      card.addEventListener('click', () => openConversation(item.id));
      card.querySelector('button').addEventListener('click', e => { e.stopPropagation(); deleteConversation(item.id); });
      $('historyGrid').appendChild(card);
    }
  } catch (err) { toast('Không tải được lịch sử: ' + err.message); }
}
async function openConversation(id) {
  if (busy) return;
  try {
    const data = await api('/api/conversations/' + encodeURIComponent(id));
    activeId = id; $('messageContainer').replaceChildren(); nav('chat');
    for (const message of data.messages) addMessage(message.content, message.role === 'user' ? 'user' : 'assistant', message.image);
  } catch (err) { toast(err.message); }
}
async function deleteConversation(id) {
  if (!confirm('Xóa cuộc trò chuyện này?')) return;
  try { await api('/api/conversations/' + encodeURIComponent(id), {method:'DELETE'}); if (activeId === id) newChat(); await loadHistory(); } catch (err) { toast(err.message); }
}
function clearImage() { currentImage = null; $('imageInput').value=''; $('imagePreview').classList.add('hidden'); $('previewImg').removeAttribute('src'); }
function selectImage(file) {
  if (!file) return;
  if (!['image/jpeg','image/png','image/webp','image/gif'].includes(file.type)) return toast('Chỉ hỗ trợ ảnh JPG, PNG, WEBP hoặc GIF.');
  if (file.size > 7*1024*1024) return toast('Ảnh quá lớn. Vui lòng chọn ảnh dưới 7 MB.');
  const reader = new FileReader(); reader.onload = () => { currentImage=reader.result; $('previewImg').src=currentImage; $('previewName').textContent=file.name; $('imagePreview').classList.remove('hidden'); }; reader.readAsDataURL(file);
}
async function sendMessage() {
  if (busy) return;
  const prompt = $('userInput').value.trim(), image = currentImage;
  if (!prompt && !image) return;
  $('userInput').value=''; $('userInput').style.height='auto'; clearImage();
  addMessage(prompt,'user',image); busy=true; $('sendBtn').disabled=true;
  const pending = addMessage('Đang suy nghĩ…','assistant');
  try {
    const result = await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:prompt,image,conversation_id:activeId})});
    activeId=result.conversation_id; pending.remove(); addMessage(result.answer,'assistant'); await loadHistory();
  } catch (err) {
    pending.remove(); addMessage('⚠️ '+err.message,'assistant');
    // Server may have saved the user message even if AI failed.
    await loadHistory();
  } finally { busy=false; $('sendBtn').disabled=false; }
}
function speakText(text) {
  if (!('speechSynthesis' in window)) return toast('Trình duyệt không hỗ trợ đọc văn bản.');
  speechSynthesis.cancel(); const speech = new SpeechSynthesisUtterance(text.replace(/\\(?:Rightarrow|dfrac|frac|\[|\]|\(|\))/g,' ').replace(/[*#`]/g,'')); speech.lang='vi-VN'; speech.rate=1; speechSynthesis.speak(speech);
}
function setupMic() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return;
  recognition = new SpeechRecognition(); recognition.lang='vi-VN'; recognition.interimResults=false;
  recognition.onresult = e => { $('userInput').value=e.results[0][0].transcript; };
  recognition.onend = recognition.onerror = () => { listening=false; $('micBtn').classList.remove('recording'); };
}
$('homeNav').onclick=()=>nav('home'); $('historyNav').onclick=()=>nav('history'); $('newChat').onclick=newChat; $('refreshHistory').onclick=loadHistory;
$('openSidebar').onclick=()=>{ $('sidebar').classList.add('open'); $('overlay').classList.add('open'); };
$('closeSidebar').onclick=$('overlay').onclick=()=>{ $('sidebar').classList.remove('open'); $('overlay').classList.remove('open'); };
$('uploadBtn').onclick=$('bannerUpload').onclick=()=>$('imageInput').click();
$('imageInput').onchange=e=>selectImage(e.target.files[0]); $('removeImage').onclick=clearImage;
$('sendBtn').onclick=sendMessage;
$('userInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}});
$('userInput').addEventListener('input',e=>{e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,120)+'px';});
for(const card of document.querySelectorAll('[data-prompt]')) card.addEventListener('click',()=>{ $('userInput').value=card.dataset.prompt; sendMessage(); });
$('micBtn').onclick=()=>{if(!recognition)return toast('Trình duyệt chưa hỗ trợ nhận diện giọng nói. Hãy thử Chrome.');try{if(listening){recognition.stop();}else{recognition.start();listening=true;$('micBtn').classList.add('recording');}}catch(err){toast('Không mở được micro: '+err.message);}};
setupMic(); loadHistory();
