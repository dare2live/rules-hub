// 解析放在 Worker 里，避免 20MB 的表格把主线程卡死。
// 只做纯计算，不碰 DOM。

try {
  importScripts('/vendor/xlsx.full.min.js');
} catch (e) {
  self.__xlsxError = String(e && e.message ? e.message : e);
}

try {
  importScripts('/vendor/mammoth.browser.min.js');
} catch (e) {
  self.__mammothError = String(e && e.message ? e.message : e);
}

function truncate(text, maxChars) {
  if (text.length <= maxChars) return { text, truncated: false, total: text.length };
  return { text: text.slice(0, maxChars), truncated: true, total: text.length };
}

function htmlToText(html) {
  return String(html)
    .replace(/<\/(p|div|h[1-6]|li|blockquote)>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(td|th)>/gi, ' | ')
    .replace(/<\/tr>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function readSheet(buffer, isCsv) {
  if (!self.XLSX) throw new Error(`表格解析库未加载：${self.__xlsxError || '未知原因'}`);
  const wb = isCsv
    ? self.XLSX.read(new TextDecoder().decode(buffer), { type: 'string' })
    : self.XLSX.read(new Uint8Array(buffer), { type: 'array' });

  const parts = [];
  for (const name of wb.SheetNames) {
    const sheet = wb.Sheets[name];
    if (!sheet) continue;
    let csv = self.XLSX.utils.sheet_to_csv(sheet, { blankrows: false });
    if (!csv.trim()) continue;
    if (csv.length > 40000) {
      csv = `${csv.slice(0, 40000)}\n... (该工作表已截断)`;
    }
    parts.push(`#### 工作表: ${name}\n\`\`\`csv\n${csv}\n\`\`\``);
  }
  return parts.join('\n\n');
}

async function readDocx(buffer) {
  if (!self.mammoth) throw new Error(`Word 解析库未加载：${self.__mammothError || '未知原因'}`);
  const { value } = await self.mammoth.convertToHtml({ arrayBuffer: buffer });
  return htmlToText(value);
}

self.onmessage = async (event) => {
  const { id, kind, buffer, maxChars } = event.data;
  try {
    let text = '';
    if (kind === 'sheet') text = readSheet(buffer, false);
    else if (kind === 'csv') text = readSheet(buffer, true);
    else if (kind === 'docx') text = await readDocx(buffer);
    else text = new TextDecoder('utf-8').decode(buffer);

    if (!text.trim()) throw new Error('没有解析出可读文本（可能是空文件或纯图片扫描件）');

    const t = truncate(text, maxChars);
    self.postMessage({ id, ok: true, text: t.text, truncated: t.truncated, total: t.total });
  } catch (err) {
    self.postMessage({ id, ok: false, error: err?.message || String(err) });
  }
};
