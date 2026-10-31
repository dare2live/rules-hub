// 浏览器端附件处理：图片压缩、PDF 直传、Office/文本在 Worker 里解析。
// 全程不经过服务端存储，也不依赖 S3。

const SHEET_EXT = new Set(['xlsx', 'xls', 'xlsm', 'xlsb', 'csv']);

let worker = null;
let seq = 0;
const pending = new Map();

function ensureWorker() {
  if (worker) return worker;
  worker = new Worker('/lib/parse-worker.js');
  worker.onmessage = (event) => {
    const { id } = event.data;
    const job = pending.get(id);
    if (!job) return;
    pending.delete(id);
    if (event.data.ok) job.resolve(event.data);
    else job.reject(new Error(event.data.error));
  };
  worker.onerror = (err) => {
    for (const job of pending.values()) job.reject(new Error(`解析进程异常：${err.message || '未知'}`));
    pending.clear();
    worker = null;
  };
  return worker;
}

function parseInWorker(kind, buffer, maxChars) {
  const w = ensureWorker();
  const id = ++seq;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    w.postMessage({ id, kind, buffer, maxChars }, [buffer]);
  });
}

function readBase64(blob) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(',')[1] || '');
    fr.onerror = () => reject(fr.error || new Error('读取文件失败'));
    fr.readAsDataURL(blob);
  });
}

// 长边压到 1568px：再大只是烧 token，模型看不出更多细节
async function shrinkImage(file) {
  if (file.type === 'image/svg+xml') return file;
  let bmp;
  try {
    bmp = await createImageBitmap(file);
  } catch {
    return file;
  }
  const maxSide = 1568;
  const longest = Math.max(bmp.width, bmp.height);
  const scale = Math.min(1, maxSide / longest);
  if (scale === 1 && file.size <= 1.2e6) {
    bmp.close?.();
    return file;
  }

  const w = Math.max(1, Math.round(bmp.width * scale));
  const h = Math.max(1, Math.round(bmp.height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bmp, 0, 0, w, h);
  bmp.close?.();

  const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.86));
  if (!blob) return file;
  return new File([blob], `${file.name.replace(/\.[^.]+$/, '')}.jpg`, { type: 'image/jpeg' });
}

function looksBinary(buffer) {
  const view = new Uint8Array(buffer.slice(0, 512));
  for (const b of view) if (b === 0) return true;
  return false;
}

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export async function processFile(file, limits) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  const maxChars = limits.maxChars || 120000;

  if (file.type.startsWith('image/')) {
    const shrunk = await shrinkImage(file);
    return {
      name: file.name,
      size: shrunk.size,
      kind: 'image',
      mime: shrunk.type || 'image/jpeg',
      data: await readBase64(shrunk),
      note: shrunk.size < file.size ? `已压缩至 ${formatSize(shrunk.size)}` : '',
    };
  }

  if (file.type === 'application/pdf' || ext === 'pdf') {
    const cap = (limits.maxPdfMB || 20) * 1024 * 1024;
    if (file.size > cap) throw new Error(`PDF 超过 ${limits.maxPdfMB}MB`);
    return {
      name: file.name,
      size: file.size,
      kind: 'pdf',
      mime: 'application/pdf',
      data: await readBase64(file),
      note: '',
    };
  }

  const cap = (limits.maxFileMB || 10) * 1024 * 1024;
  if (file.size > cap) throw new Error(`文件超过 ${limits.maxFileMB}MB`);

  if (ext === 'doc') throw new Error('不支持旧版 .doc，请另存为 .docx');

  let kind = 'text';
  if (SHEET_EXT.has(ext)) kind = ext === 'csv' ? 'csv' : 'sheet';
  else if (ext === 'docx') kind = 'docx';

  const buffer = await file.arrayBuffer();
  if (kind === 'text' && looksBinary(buffer)) throw new Error('看起来是二进制文件，暂不支持');

  const res = await parseInWorker(kind, buffer, maxChars);
  return {
    name: file.name,
    size: file.size,
    kind: 'text',
    text: res.text,
    note: res.truncated ? `已截断（原文 ${res.total} 字符）` : '',
  };
}
