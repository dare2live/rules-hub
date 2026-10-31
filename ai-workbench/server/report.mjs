// 每日用量日报。由 systemd timer 触发，不依赖常驻进程。
// 和 Cloudflare 上的 Cron Trigger 跑的是同一套逻辑。

import { fetchUsage } from '../src/analytics.js';
import { formatReport, sendTelegram } from '../src/telegram.js';

const env = process.env;

if (!env.TG_BOT_TOKEN || !env.TG_CHAT_ID) {
  console.error('TG_BOT_TOKEN / TG_CHAT_ID 未配置，跳过');
  process.exit(0);
}

const usage = await fetchUsage(env);
const text = formatReport(usage);
const result = await sendTelegram(env, text);

console.log(text.replace(/<[^>]+>/g, ''));

if (!result.ok) {
  console.error('推送失败：', JSON.stringify(result).slice(0, 500));
  process.exit(1);
}
