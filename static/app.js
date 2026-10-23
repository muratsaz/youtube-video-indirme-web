const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="app-token"]').content;
let jobs = [], filter = 'all', previousRender = '', pollTimer, toastTimer;
const activeStates = new Set(['queued', 'preparing', 'downloading', 'processing', 'cancelling']);
const labels = {queued: 'Sırada', preparing: 'Video hazırlanıyor…', downloading: 'İndiriliyor', processing: 'Dosya hazırlanıyor…', cancelling: 'İptal ediliyor…', done: 'Tamamlandı', error: 'İndirilemedi', cancelled: 'İptal edildi'};
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHtml = (text) => String(text ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
function bytes(value) { if (!value) return ''; const unit = Math.min(3, Math.floor(Math.log(value) / Math.log(1024))); return `${(value / 1024 ** unit).toLocaleString('tr-TR', {maximumFractionDigits: 1})} ${['B', 'KB', 'MB', 'GB'][unit]}`; }
function duration(seconds) { if (!seconds) return ''; return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`; }
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4500); }
function errorMessage(message) { $('#form-error').textContent = message; $('#form-error').hidden = !message; }
async function api(path, body = {}) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-App-Token': token}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Bilgileri kontrol edip yeniden dene.');
  return data;
}
function render() {
  $('#total-count').textContent = jobs.length;
  $('#nav-count').textContent = jobs.filter(job => job.status === 'done').length;
  const visible = jobs.filter(job => filter === 'all' || (filter === 'active' ? activeStates.has(job.status) : job.status === 'done'));
  const signature = JSON.stringify(visible);
  if (signature === previousRender) return;
  previousRender = signature;
  if (!visible.length) {
    $('#jobs').innerHTML = `<div class="empty-state"><span class="empty-icon">${icon('download')}</span><h3>${filter === 'all' ? 'İlk videona yer açtık.' : filter === 'active' ? 'Şu an devam eden indirme yok.' : 'Tamamlanan videolar burada olacak.'}</h3><p>${filter === 'all' ? 'Yukarıya bir bağlantı yapıştır; indirmelerini burada takip et.' : 'Yeni bir video indirmek için yukarıya bağlantısını yapıştır.'}</p><span class="empty-shortcut">Bağlantı + bir tık. Hepsi bu.</span></div>`;
    return;
  }
  $('#jobs').innerHTML = visible.map(job => {
    const active = activeStates.has(job.status);
    const percentage = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const thumbnail = /^https:\/\/i\.ytimg\.com\/vi\/[A-Za-z0-9_-]{11}\/mqdefault\.jpg$/.test(job.thumbnail || '') ? `<img class="job-thumbnail" src="${escapeHtml(job.thumbnail)}" alt="" loading="lazy">` : `<span class="job-thumbnail">${icon(job.kind === 'audio' ? 'music' : 'video')}</span>`;
    const meta = [job.channel, duration(job.duration)].filter(Boolean).map(escapeHtml).join(' · ');
    const detail = job.status === 'done' ? `${bytes(job.size)} · Bilgisayarına kaydedildi` : job.status === 'downloading' ? [bytes(job.downloaded_bytes), job.total_bytes ? `/ ${bytes(job.total_bytes)}` : '', job.speed ? `· ${bytes(job.speed)}/sn` : '', job.eta ? `· ~${Math.ceil(job.eta / 60)} dk` : ''].filter(Boolean).join(' ') : job.status === 'processing' ? 'Ses ve görüntü birleştiriliyor veya dosya dönüştürülüyor.' : job.status === 'queued' ? 'Sıran geldiğinde otomatik başlayacak.' : job.status === 'preparing' ? 'YouTube bağlantısı kontrol ediliyor.' : '';
    let actions = '';
    if (job.status === 'done') actions = `<button data-action="reveal" data-id="${job.id}">Klasörde göster ↗</button>`;
    else if (job.status === 'error' || job.status === 'cancelled') actions = `<button data-action="retry" data-id="${job.id}">Yeniden dene ↻</button>`;
    else if (active && job.status !== 'cancelling') actions = `<button data-action="cancel" data-id="${job.id}">İptal et</button>`;
    return `<article class="job">${thumbnail}<div class="job-main"><div class="job-top"><h3 class="job-title" title="${escapeHtml(job.title)}">${escapeHtml(job.title)}</h3><span class="job-status ${escapeHtml(job.status)}">${escapeHtml(labels[job.status] || job.status)}${job.status === 'downloading' && job.total_bytes ? ` · %${Math.floor(percentage)}` : ''}</span></div>${meta ? `<div class="job-channel">${meta}</div>` : ''}<div class="job-tags"><span>${job.kind === 'audio' ? 'MP3 · 192 kbps' : 'MP4'}</span>${job.kind === 'video' ? `<span>${job.quality === 'best' ? 'En yüksek kalite' : `En fazla ${escapeHtml(job.quality)}p`}</span>` : ''}</div>${active ? `<div class="job-progress ${['queued','preparing','processing','cancelling'].includes(job.status) || !job.total_bytes ? 'indeterminate' : ''}" role="progressbar" aria-label="İndirme ilerlemesi" ${job.status === 'downloading' && job.total_bytes ? `aria-valuenow="${percentage}" aria-valuemin="0" aria-valuemax="100"` : ''}><div data-progress="${percentage}"></div></div>` : ''}${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ''}<div class="job-details"><span>${escapeHtml(detail)}</span><div class="job-actions">${actions}</div></div></div></article>`;
  }).join('');
  document.querySelectorAll('[data-progress]').forEach(element => { if (!element.parentElement.classList.contains('indeterminate')) element.style.width = `${element.dataset.progress}%`; });
}
async function refresh() {
  clearTimeout(pollTimer);
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error();
    const state = await response.json();
    jobs = state.jobs;
    $('#save-path').textContent = state.folder;
    $('#save-path').title = state.folder;
    $('#connection').innerHTML = '<i></i>Bilgisayarına bağlı';
    $('#connection').classList.remove('offline');
    if (!state.ffmpeg || !state.node) errorMessage('İndirme araçları eksik. README dosyasındaki kurulum adımlarını kontrol et.');
    render();
  } catch {
    $('#connection').innerHTML = '<i></i>Bağlantı kesildi';
    $('#connection').classList.add('offline');
    errorMessage('Uygulamaya ulaşılamıyor. Baslat dosyasına çift tıklayıp sayfayı yenile.');
  } finally { pollTimer = setTimeout(refresh, jobs.some(job => activeStates.has(job.status)) ? 1000 : 4000); }
}
$('#download-form').addEventListener('submit', async event => {
  event.preventDefault(); errorMessage('');
  const button = $('#download-button'); button.disabled = true;
  try {
    await api('/api/downloads', {url: $('#video-url').value.trim(), kind: $('input[name="kind"]:checked').value, quality: $('#quality').value});
    $('#video-url').value = '';
    filter = 'all'; document.querySelectorAll('[data-filter]').forEach(button => button.classList.toggle('active', button.dataset.filter === filter));
    toast('İndirme eklendi. Tamamlanınca dosyan otomatik kaydedilecek.');
    await refresh();
  } catch (error) { errorMessage(error.message); } finally { button.disabled = false; }
});
$('#paste-button').addEventListener('click', async () => {
  try { $('#video-url').value = await navigator.clipboard.readText(); $('#video-url').focus(); errorMessage(''); }
  catch { $('#video-url').focus(); toast('Bağlantıyı Ctrl + V ile yapıştırabilirsin.'); }
});
document.querySelectorAll('input[name="kind"]').forEach(input => input.addEventListener('change', () => {
  const audio = input.value === 'audio'; $('#quality').disabled = audio;
  $('#quality-hint').textContent = audio ? 'Ses, 192 kbps MP3 olarak kaydedilir.' : 'Seçilen kalite yoksa en iyi alt kalite indirilir.';
}));
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  filter = button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === button)); previousRender = ''; render();
}));
$('#jobs').addEventListener('click', async event => {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const job = jobs.find(job => job.id === button.dataset.id); if (!job) return;
  button.disabled = true;
  try {
    if (button.dataset.action === 'retry') await api('/api/downloads', {url: job.url, kind: job.kind, quality: job.quality});
    else await api(`/api/downloads/${job.id}/${button.dataset.action}`);
    if (button.dataset.action === 'reveal') toast('Dosyanın bulunduğu klasör açıldı.');
    await refresh();
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
});
async function openFolder() { try { await api('/api/open-folder'); toast('İndirme klasörün açıldı.'); } catch (error) { toast(error.message); } }
$('#open-folder').addEventListener('click', openFolder);
$('#sidebar-folder').addEventListener('click', openFolder);
document.querySelectorAll('.help-trigger').forEach(button => button.addEventListener('click', () => $('#help-dialog').showModal()));
document.querySelectorAll('.close-dialog, .close-help').forEach(button => button.addEventListener('click', () => $('#help-dialog').close()));
$('#help-dialog').addEventListener('click', event => { if (event.target === $('#help-dialog')) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
refresh();
