/***********************************

The Economist 解锁（Rules Hub 自托管版）

【App 有两条链路】

经济学人 App 的正文不来自 www.economist.com，而是移动端 GraphQL 网关：

    GET https://api.economist.com/teg/content/b2c-mobile/cp2-gateway/graphql
        ?operationName=ArticlesQuery&variables=...

裸请求返回 401 Invalid credentials（Kong 网关，路由真实存在），说明这是
App 专属接口，网页版不经过它。只把 www.economist.com 放进 [mitm] 拦不到。

启动时还会拉机构订阅标记：

    GET https://www.economist.com/api/bulk-subscriber
    -> {"isBulkSubscriber":false,"meta":{"client_ip":"x.x.x.x"}}

【自检地址】

1) https://www.economist.com/api/bulk-subscriber
   看到 "isBulkSubscriber":true -> 证书、MITM、重写三件套正常。
2) https://api.economist.com/__mitm_test
   看到 "MITM OK" -> 该域名已被解密。
3) https://www.economist.com/api/bulk-subscriber?log=1
   探针报告：命中请求、可疑字段清单、文章正文统计。

【本版探针在查什么】

重装 App 后拿到了完整的 ArticlesQuery 响应（360KB），但按已知字段名
一个都没改到，说明付费墙用的不是我猜的名字。所以这版改成两步：

1. 按关键词扫全树：premium / subscri / paywall / access / entitle /
   locked / restrict / tier / member / gated / abridg / truncat / preview / free
   每个不同的字段名只留一条示例，看名字就能知道该改哪个。
2. 统计每篇文章的 wordCount 和 body 实际文本字数。如果 wordCount 是 800
   而文本只有 200 字，说明正文是服务端截断的——那种情况客户端改不出来。

【文件名为什么带版本号】

QX 对远程脚本按 URL 缓存。只改内容、不改文件名时，就算在 QX 里点了
「更新资源」，拿到的还是旧脚本本体——线上改了等于没改，而且不报错。
所以每次改逻辑都要换文件名（v4 -> v5 ...）。

[rewrite_local]
^https:\/\/www\.economist\.com\/api\/bulk-subscriber url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/api\.economist\.com\/teg\/content\/b2c-mobile\/cp2-gateway\/graphql url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/www\.economist\.com\/[a-z-]+\/[0-9]{4}\/[0-9]{2}\/[0-9]{2}\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/www\.economist\.com\/interactive\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/api\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/www\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js

^https:\/\/login\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/id\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js
^https:\/\/my\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v6.js

[mitm]
hostname = www.economist.com, api.economist.com, login.economist.com, id.economist.com, my.economist.com

***********************************/

var url = $request.url || '';
var body = $response.body;

// ===================== GraphQL 正文接口 =====================

// 字段名里带这些词的，一律记一条示例出来
var INTERESTING = /(premium|subscri|paywall|access|entitle|locked|restrict|tier|member|gated|abridg|truncat|preview|free)/i;

function handleGraphQL() {
    var obj;
    try {
        obj = JSON.parse(body);
    } catch (e) {
        console.log('Economist: GraphQL 响应不是 JSON，原样放行');
        $done({});
        return;
    }

    var op = decodeURIComponent((url.match(/[?&]operationName=([^&]+)/) || [])[1] || 'unknown');
    var ctx = { hits: [], seen: {}, changed: [], visited: 0 };

    walk(obj, 'root', ctx, 0);

    var out = [];
    out.push('# op=' + op + '  ' + body.length + 'B  ' + new Date().toISOString());
    out.push('# 改动 ' + ctx.changed.length + ' 处');
    for (var i = 0; i < ctx.changed.length && i < 20; i++) {
        out.push('  ' + ctx.changed[i]);
    }
    out.push('');
    out.push('=== 可疑字段（按字段名去重，各留一条示例）===');
    if (ctx.hits.length) {
        for (var j = 0; j < ctx.hits.length && j < 60; j++) {
            out.push(ctx.hits[j]);
        }
    } else {
        out.push('(没有匹配到任何关键词)');
    }

    var stats = articleStats(obj);
    if (stats.length) {
        out.push('');
        out.push('=== 文章正文统计（wordCount vs 实际文本）===');
        out = out.concat(stats);
    }

    var text = out.join('\n');
    if (text.length > 4000) {
        text = text.slice(0, 4000) + '\n…（已截断）';
    }
    pushProbe(text);

    if (ctx.changed.length > 0) {
        $done({ body: JSON.stringify(obj) });
    } else {
        $done({});
    }
}

// 一次遍历干两件事：记下可疑字段名，顺手把付费墙类布尔翻正
function walk(node, path, ctx, depth) {
    if (!node || typeof node !== 'object' || depth > 16) {
        return;
    }
    if (ctx.visited++ > 150000) {
        return;
    }

    if (Object.prototype.toString.call(node) === '[object Array]') {
        for (var i = 0; i < node.length; i++) {
            walk(node[i], path + '[' + i + ']', ctx, depth + 1);
        }
        return;
    }

    for (var k in node) {
        if (!Object.prototype.hasOwnProperty.call(node, k)) {
            continue;
        }
        var v = node[k];
        var p = path + '.' + k;

        if (INTERESTING.test(k)) {
            // 布尔值按「名字+值」去重：同一个字段既有 true 又有 false 时，
            // 两条都留下，否则只看得到第一条，看不出差异。
            var dk = k + (typeof v === 'boolean' ? ':' + v : '');
            if (!ctx.seen[dk]) {
                ctx.seen[dk] = 1;
                ctx.hits.push(p + ' = ' + brief(v));
            }
        }

        var kind = flagKind(k);
        if (kind && typeof v === 'boolean') {
            var want = (kind === 't');
            if (v !== want) {
                node[k] = want;
                ctx.changed.push(p + '  ' + v + ' -> ' + want);
            }
            continue;
        }

        if (v && typeof v === 'object') {
            walk(v, p, ctx, depth + 1);
        }
    }
}

function brief(v) {
    if (v === null) {
        return 'null';
    }
    if (Object.prototype.toString.call(v) === '[object Array]') {
        return '[数组 ' + v.length + ' 项]';
    }
    if (typeof v === 'object') {
        return '{对象}';
    }
    var s = String(v);
    if (s.length > 70) {
        s = s.slice(0, 70) + '…';
    }
    return (typeof v === 'string') ? '"' + s + '"' : s;
}

// wordCount 是文章真实长度，body 里 text 的总长是实际下发的字数。
// 两个差得远，就是服务端截断了正文。
function articleStats(obj) {
    var out = [];
    var list = null;
    try {
        var d = obj.data || {};
        if (Object.prototype.toString.call(d.findArticles) === '[object Array]') {
            list = d.findArticles;
        } else if (d.findArticle) {
            list = [d.findArticle];
        }
    } catch (e) {}
    if (!list) {
        return out;
    }
    for (var i = 0; i < list.length && i < 8; i++) {
        var a = list[i];
        if (!a || typeof a !== 'object') {
            continue;
        }
        var segs = 0;
        var chars = 0;
        if (Object.prototype.toString.call(a.body) === '[object Array]') {
            segs = a.body.length;
            for (var j = 0; j < a.body.length; j++) {
                var c = a.body[j];
                if (c && typeof c.text === 'string') {
                    chars += c.text.length;
                }
            }
        }
        out.push('[' + i + '] "' + String(a.headline || a.url || '?').slice(0, 44) + '"' +
            '  wordCount=' + (a.wordCount === undefined || a.wordCount === null ? '?' : a.wordCount) +
            '  body=' + segs + ' 段  文本 ' + chars + ' 字');
    }
    return out;
}

// 字段名 -> 目标值。去掉下划线和大小写后比对，兼容 is_premium / isPremium。
var FLAG_FALSE = toSet('isPremium,isPaid,isLocked,isPaywalled,paywalled,' +
    'requiresSubscription,requiresPayment,isGated,gated,isRestricted,restricted,' +
    'isSubscriberOnly,subscriberOnly,subscriberContent,isPremiumContent,' +
    'hasPaywall,isPaywall,showPaywall,paywallEnabled,isRegistrationRequired,' +
    'registrationRequired,needsSubscription,isMetered,metered,isBlocked');

var FLAG_TRUE = toSet('isSubscriber,isEntitled,entitled,hasAccess,hasSubscription,' +
    'hasFullAccess,canRead,isAccessibleForFree,isAccessible,isUnlocked,unlocked,' +
    'isFree,isFreeArticle,isBulkSubscriber');

function toSet(csv) {
    var o = {};
    var a = csv.split(',');
    for (var i = 0; i < a.length; i++) {
        o[a[i].toLowerCase()] = 1;
    }
    return o;
}

function flagKind(k) {
    var n = String(k).toLowerCase().replace(/[_-]/g, '');
    if (FLAG_FALSE[n]) {
        return 'f';
    }
    if (FLAG_TRUE[n]) {
        return 't';
    }
    return '';
}

// ===================== 机构订阅标记 =====================

function handleBulk() {
    var obj;
    try {
        obj = JSON.parse(body);
    } catch (e) {
        $done({});
        return;
    }
    if (obj && typeof obj === 'object' && 'isBulkSubscriber' in obj) {
        obj.isBulkSubscriber = true;
        if (!obj.meta || typeof obj.meta !== 'object') {
            obj.meta = {};
        }
        $done({ body: JSON.stringify(obj) });
    } else {
        $done({});
    }
}

// ===================== 账户 / 登录域名 =====================
// login / id / my 这三个域名一直没拦过。App 的订阅状态很可能来自这里，
// 而不是文章响应——因为文章响应里全文完整、一个付费墙字段都没有。

function handleAccount(label) {
    var obj;
    try {
        obj = JSON.parse(body);
    } catch (e) {
        pushProbe('# host=' + label + '  ' + (body ? body.length : 0) + 'B  (非 JSON)');
        $done({});
        return;
    }

    var ctx = { hits: [], seen: {}, changed: [], visited: 0 };
    walk(obj, 'root', ctx, 0);

    var out = [];
    out.push('# host=' + label + '  ' + body.length + 'B  ' + new Date().toISOString());
    out.push('# 改动 ' + ctx.changed.length + ' 处');
    for (var i = 0; i < ctx.changed.length && i < 20; i++) {
        out.push('  ' + ctx.changed[i]);
    }
    out.push('=== 可疑字段 ===');
    out = out.concat(ctx.hits.length ? ctx.hits.slice(0, 40) : ['(无)']);
    out.push('=== 全部字段 ===');
    out = out.concat(structure(obj, 'root', [], 0).slice(0, 80));

    var text = out.join('\n');
    if (text.length > 4000) {
        text = text.slice(0, 4000) + '\n…（已截断）';
    }
    pushProbe(text);

    if (ctx.changed.length > 0) {
        $done({ body: JSON.stringify(obj) });
    } else {
        $done({});
    }
}

// 把整个响应摊平列出，层级太深就停
function structure(node, path, out, depth) {
    if (!node || typeof node !== 'object' || depth > 8 || out.length > 140) {
        return out;
    }
    if (Object.prototype.toString.call(node) === '[object Array]') {
        var lim = Math.min(node.length, 3);
        for (var i = 0; i < lim; i++) {
            structure(node[i], path + '[' + i + ']', out, depth + 1);
        }
        if (node.length > lim) {
            out.push(path + '[] 共 ' + node.length + ' 项');
        }
        return out;
    }
    for (var k in node) {
        if (!Object.prototype.hasOwnProperty.call(node, k)) {
            continue;
        }
        var v = node[k];
        var p = path + '.' + k;
        if (v && typeof v === 'object') {
            structure(v, p, out, depth + 1);
        } else {
            out.push(p + ' = ' + brief(v));
        }
    }
    return out;
}

// ===================== 网页正文 =====================

function handleHtml() {
    var trimmed = String(body).replace(/^\s+/, '');
    if (trimmed.charAt(0) !== '<') {
        $done({});
        return;
    }
    try {
        var out = stripDivById(body, 'tp-regwall');
        out = unlockScroll(out);
        if (out === body) {
            $done({});
        } else {
            $done({ body: out });
        }
    } catch (e) {
        console.log('Economist: HTML 处理失败，原样放行 -> ' + e);
        $done({});
    }
}

function stripDivById(html, id) {
    var open = new RegExp('<div[^>]*\\bid\\s*=\\s*["\']' + id + '["\'][^>]*>', 'i');
    var m = open.exec(html);
    if (!m) {
        return html;
    }
    var start = m.index;
    var i = start + m[0].length;
    var depth = 1;
    var tag = /<\/?div\b[^>]*>/gi;
    tag.lastIndex = i;
    var t;
    while (depth > 0 && (t = tag.exec(html)) !== null) {
        if (t[0].charAt(1) === '/') {
            depth -= 1;
        } else {
            depth += 1;
        }
        i = t.index + t[0].length;
    }
    return html.slice(0, start) + html.slice(i);
}

function unlockScroll(html) {
    return html.replace(/<body([^>]*?)(\s+style=)(["'])([^"']*)\3/gi,
        function (all, pre, eq, q, css) {
            var cleaned = css.replace(/overflow(-y)?\s*:\s*hidden\s*;?/gi, '').trim();
            return cleaned ? '<body' + pre + eq + q + cleaned + q : '<body' + pre;
        });
}

// ===================== 探针 =====================

function shouldRecord(u) {
    return !/\.(?:js|css|png|jpe?g|gif|svg|woff2?|ttf|eot|ico|webp|avif|mp4|m3u8|map)(?:[?#]|$)/i.test(u);
}

function meta() {
    var p = [];
    try {
        p.push('m=' + ($request.method || '?'));
    } catch (e) {}
    try {
        p.push('s=' + ($response.statusCode || 0));
    } catch (e) {}
    var h = {};
    try {
        h = $response.headers || {};
    } catch (e) {}
    var ct = pickHeader(h, 'content-type');
    if (ct) {
        p.push('ct=' + String(ct).split(';')[0]);
    }
    p.push('ce=' + (pickHeader(h, 'content-encoding') || '-'));
    return p.join(' ');
}

function pickHeader(h, name) {
    for (var k in h) {
        if (k.toLowerCase() === name) {
            return h[k];
        }
    }
    return '';
}

function record(u, size) {
    if (!shouldRecord(u)) {
        return;
    }
    var m = /^https?:\/\/([^\/?#]+)(\/[^?#]*)?/.exec(u);
    if (!m) {
        return;
    }
    var op = (u.match(/[?&]operationName=([^&]+)/) || [])[1];
    var key = m[1] + (m[2] || '/') + (op ? '  op=' + op : '');
    var line = key + '  [body=' + size + ']  ' + meta();

    var raw = prefsGet('econ.hits') || '';
    var lines = raw ? raw.split('\n') : [];
    var hit = -1;
    for (var i = 0; i < lines.length; i++) {
        if (lines[i].indexOf(key) === 0) {
            hit = i;
            break;
        }
    }
    if (hit >= 0) {
        lines[hit] = line;
    } else {
        lines.push(line);
    }
    if (lines.length > 60) {
        lines = lines.slice(lines.length - 60);
    }
    prefsSet('econ.hits', lines.join('\n'));
}

// 保留最近 3 次响应，避免被后续的预取请求冲掉
function pushProbe(text) {
    var all = prefsGet('econ.probe') || '';
    var parts = all ? all.split('\n@@@\n') : [];
    parts.push(text);
    if (parts.length > 3) {
        parts = parts.slice(parts.length - 3);
    }
    prefsSet('econ.probe', parts.join('\n@@@\n'));
}

function dumpProbe() {
    prefsSet('econ.ping', 'ping-' + new Date().getTime());
    var ping = prefsGet('econ.ping');
    var storeOk = !!ping && ping.indexOf('ping-') === 0;

    var hits = prefsGet('econ.hits') || '';
    var probe = prefsGet('econ.probe') || '';

    var out = [];
    out.push('# 存储自检: ' + (storeOk ? 'OK' : '不可用 —— 报告为空不代表没有请求'));
    out.push('# 时间: ' + new Date().toISOString());
    out.push('');
    out.push('=== 命中的请求 ===');
    out.push(hits || '(一条都没有：检查 MITM 名单、重写资源是否已更新)');
    out.push('');
    out.push('=== 最近 3 次响应（GraphQL 正文 / 账户）===');
    if (probe) {
        out.push(probe.split('\n@@@\n').join('\n\n----------\n\n'));
    } else {
        out.push('(没有记录到)');
    }

    $done({
        body: out.join('\n'),
        headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
}

function mitmTest() {
    $done({
        body: 'MITM OK: api.economist.com 已被 QX 解密，脚本能拿到它的响应。\n' +
            '时间: ' + new Date().toISOString() + '\n' +
            '如果 App 里仍然弹墙，请打开\n' +
            'https://www.economist.com/api/bulk-subscriber?log=1\n' +
            '把报告发出来。',
        headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
}

function prefsGet(key) {
    try {
        if (typeof $prefs !== 'undefined' && $prefs.valueForKey) {
            return $prefs.valueForKey(key) || '';
        }
    } catch (e) {}
    return '';
}

function prefsSet(key, value) {
    try {
        if (typeof $prefs !== 'undefined' && $prefs.setValueForKey) {
            $prefs.setValueForKey(value, key);
        }
    } catch (e) {}
}

// ===================== 执行入口（必须在末尾）=====================
// 函数声明会提升，但 FLAG_FALSE / FLAG_TRUE 这类 var 赋值不会。
// 入口写在前面的话，第一次进 flagKind 时字段表还是 undefined，
// 脚本静默抛异常、QX 拿不到 $done，表现为 App 一直转圈。

if (/[?&]log=1(?:&|$)/.test(url)) {
    dumpProbe();
} else if (url.indexOf('/__mitm_test') >= 0) {
    mitmTest();
} else if (url.indexOf('cp2-gateway/graphql') >= 0) {
    record(url, body ? body.length : 0);
    if (body) {
        handleGraphQL();
    } else {
        $done({});
    }
} else if (url.indexOf('/api/bulk-subscriber') >= 0) {
    record(url, body ? body.length : 0);
    if (body) {
        handleBulk();
    } else {
        $done({});
    }
} else if (url.indexOf('login.economist.com') >= 0 ||
           url.indexOf('id.economist.com') >= 0 ||
           url.indexOf('my.economist.com') >= 0) {
    record(url, body ? body.length : 0);
    if (body) {
        handleAccount((url.match(/^https?:\/\/([^\/]+)/) || [])[1] || 'account');
    } else {
        $done({});
    }
} else if (!body) {
    record(url, 0);
    $done({});
} else {
    record(url, body.length);
    handleHtml();
}
