// 两家 provider 的请求构造 + 统一 SSE 协议。
// 前端只认一种事件流，避免在浏览器里写两套解析器。

export const SSE_HEADERS = {
  'content-type': 'text/event-stream; charset=utf-8',
  'cache-control': 'no-cache, no-transform',
  connection: 'keep-alive',
  'x-accel-buffering': 'no',
};

const CATALOG = [
  { id: 'claude-sonnet-4-5', provider: 'anthropic', label: 'Claude Sonnet 4.5', tier: 'pro' },
  { id: 'claude-haiku-4-5', provider: 'anthropic', label: 'Claude Haiku 4.5', tier: 'fast' },
  { id: 'gemini-2.5-flash', provider: 'google', label: 'Gemini 2.5 Flash', tier: 'fast' },
  { id: 'gemini-2.5-pro', provider: 'google', label: 'Gemini 2.5 Pro', tier: 'pro' },
];

function parseModelList(raw) {
  if (!raw) return null;
  const text = String(raw).trim();
  if (!text) return null;
  if (text.startsWith('[')) {
    try {
      const arr = JSON.parse(text);
      return arr.map((m) => (typeof m === 'string' ? { id: m } : m)).filter((m) => m?.id);
    } catch {
      return null;
    }
  }
  return text.split(',').map((s) => s.trim()).filter(Boolean).map((id) => ({ id }));
}

// 未配置密钥的渠道直接不出现，避免朋友选中后报错
export function modelsFor(env, role) {
  const custom = parseModelList(env.MODELS);
  let list = (custom || CATALOG).map((m) => {
    const base = CATALOG.find((c) => c.id === m.id);
    const provider = m.provider || base?.provider || (m.id.startsWith('gemini') ? 'google' : 'anthropic');
    return {
      id: m.id,
      provider,
      label: m.label || base?.label || m.id,
      tier: m.tier || base?.tier || 'pro',
    };
  });

  list = list.filter((m) => (m.provider === 'anthropic' ? !!env.ANTHROPIC_API_KEY : !!env.GOOGLE_API_KEY));

  if (role !== 'admin') {
    const allowed = parseModelList(env.FRIEND_MODELS);
    if (allowed) {
      const ids = new Set(allowed.map((m) => m.id));
      list = list.filter((m) => ids.has(m.id));
    } else {
      list = list.filter((m) => m.tier === 'fast');
    }
  }
  return list;
}

function gatewayBase(env) {
  if (!env.CF_ACCOUNT_ID || !env.CF_GATEWAY_ID) {
    throw new Error('CF_ACCOUNT_ID / CF_GATEWAY_ID 未配置');
  }
  return `https://gateway.ai.cloudflare.com/v1/${env.CF_ACCOUNT_ID}/${env.CF_GATEWAY_ID}`;
}

function customCost(env, provider) {
  const inM = Number.parseFloat(env[`COST_${provider.toUpperCase()}_IN`] ?? '');
  const outM = Number.parseFloat(env[`COST_${provider.toUpperCase()}_OUT`] ?? '');
  if (!Number.isFinite(inM) || !Number.isFinite(outM)) return null;
  return { per_token_in: inM / 1e6, per_token_out: outM / 1e6 };
}

function aigHeaders(env, provider) {
  const h = {};
  if (env.CF_AIG_TOKEN) h['cf-aig-authorization'] = `Bearer ${env.CF_AIG_TOKEN}`;
  // BYOK 下 AI Gateway 的 cost 可能恒为 0，用自定义单价兜底（单位：USD / 1M tokens）
  const cost = customCost(env, provider);
  if (cost) h['cf-aig-custom-cost'] = JSON.stringify(cost);
  return h;
}

function toAnthropicMessage(m) {
  const blocks = [];
  for (const a of m.attachments || []) {
    if (a.kind === 'image') {
      blocks.push({ type: 'image', source: { type: 'base64', media_type: a.mime, data: a.data } });
    } else if (a.kind === 'pdf') {
      blocks.push({ type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: a.data } });
    }
  }
  if (m.text) blocks.push({ type: 'text', text: m.text });
  if (!blocks.length) blocks.push({ type: 'text', text: '(空消息)' });
  return { role: m.role === 'assistant' ? 'assistant' : 'user', content: blocks };
}

function toGoogleContent(m) {
  const parts = [];
  for (const a of m.attachments || []) {
    if (a.kind === 'image' || a.kind === 'pdf') {
      parts.push({ inlineData: { mimeType: a.mime, data: a.data } });
    }
  }
  if (m.text) parts.push({ text: m.text });
  if (!parts.length) parts.push({ text: '(空消息)' });
  return { role: m.role === 'assistant' ? 'model' : 'user', parts };
}

export function buildRequest(env, { provider, model, messages, system, maxTokens, stream = true }) {
  const sys = system || env.SYSTEM_PROMPT || '';
  if (provider === 'anthropic') {
    if (!env.ANTHROPIC_API_KEY) throw new Error('ANTHROPIC_API_KEY 未配置');
    const body = { model, max_tokens: maxTokens, stream, messages: messages.map(toAnthropicMessage) };
    if (sys) body.system = sys;
    return {
      url: `${gatewayBase(env)}/anthropic/v1/messages`,
      init: {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-api-key': env.ANTHROPIC_API_KEY,
          'anthropic-version': '2023-06-01',
          ...aigHeaders(env, 'anthropic'),
        },
        body: JSON.stringify(body),
      },
    };
  }

  if (provider === 'google') {
    if (!env.GOOGLE_API_KEY) throw new Error('GOOGLE_API_KEY 未配置');
    const ver = env.GOOGLE_API_VERSION || 'v1beta';
    const modelId = String(model).replace(/^models\//, '');
    const body = { contents: messages.map(toGoogleContent) };
    if (sys) body.systemInstruction = { parts: [{ text: sys }] };
    body.generationConfig = { maxOutputTokens: maxTokens };
    return {
      url: `${gatewayBase(env)}/google-ai-studio/${ver}/models/${modelId}:${
        stream ? 'streamGenerateContent?alt=sse' : 'generateContent'
      }`,
      init: {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-goog-api-key': env.GOOGLE_API_KEY,
          ...aigHeaders(env, 'google'),
        },
        body: JSON.stringify(body),
      },
    };
  }

  throw new Error(`不支持的 provider: ${provider}`);
}

const emit = (obj) => `data: ${JSON.stringify(obj)}\n\n`;

// 统一协议：
//   {"t":"d","v":"增量文本"}
//   {"t":"u","in":123,"out":45}
//   {"t":"e","msg":"错误"}
//   {"t":"done"}
export function normalizeStream(provider) {
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  let buf = '';
  let inTok = 0;
  let outTok = 0;
  let finished = false;

  const enqueue = (controller, obj) => controller.enqueue(encoder.encode(emit(obj)));

  const handle = (controller, line) => {
    if (!line.startsWith('data:')) return;
    const raw = line.slice(5).trim();
    if (!raw || raw === '[DONE]') return;
    let ev;
    try {
      ev = JSON.parse(raw);
    } catch {
      return;
    }

    if (provider === 'anthropic') {
      if (ev.type === 'message_start') {
        inTok = ev.message?.usage?.input_tokens ?? inTok;
        outTok = ev.message?.usage?.output_tokens ?? outTok;
      } else if (ev.type === 'content_block_delta') {
        if (ev.delta?.type === 'text_delta' && ev.delta.text) {
          enqueue(controller, { t: 'd', v: ev.delta.text });
        }
      } else if (ev.type === 'message_delta') {
        if (typeof ev.usage?.output_tokens === 'number') outTok = ev.usage.output_tokens;
      } else if (ev.type === 'error') {
        enqueue(controller, { t: 'e', msg: ev.error?.message || ev.error?.type || '上游返回错误' });
      } else if (ev.type === 'message_stop') {
        finished = true;
        enqueue(controller, { t: 'u', in: inTok, out: outTok });
        enqueue(controller, { t: 'done' });
      }
      return;
    }

    // google
    if (ev.error) {
      enqueue(controller, { t: 'e', msg: ev.error.message || '上游返回错误' });
      return;
    }
    if (ev.promptFeedback?.blockReason) {
      enqueue(controller, { t: 'e', msg: `请求被拦截：${ev.promptFeedback.blockReason}` });
    }
    for (const part of ev.candidates?.[0]?.content?.parts || []) {
      if (part.thought) continue;
      if (typeof part.text === 'string' && part.text) enqueue(controller, { t: 'd', v: part.text });
    }
    if (ev.usageMetadata) {
      inTok = ev.usageMetadata.promptTokenCount ?? inTok;
      outTok = ev.usageMetadata.candidatesTokenCount ?? outTok;
    }
  };

  return new TransformStream({
    transform(chunk, controller) {
      buf += decoder.decode(chunk, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx).replace(/\r$/, '');
        buf = buf.slice(idx + 1);
        handle(controller, line);
      }
    },
    flush(controller) {
      if (buf.trim()) handle(controller, buf.replace(/\r$/, ''));
      if (!finished) {
        enqueue(controller, { t: 'u', in: inTok, out: outTok });
        enqueue(controller, { t: 'done' });
      }
    },
  });
}
