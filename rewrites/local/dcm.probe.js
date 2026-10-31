/***********************************

端传媒（Initium）探针 —— 临时诊断用，定位到接口后即删

【为什么要它】

原来那条重写拦的是 app.theinitium.com，而这个域名已经没有任何 DNS 记录了：

    dig app.theinitium.com  ->  空

域名下线，规则永远匹配不上，脚本再新也没用。上游 Yuheng0101 的脚本
内容与我们仓库里的逐字一致，不是没更新，是它本身已经废了。

端传媒现在主站是 theinitium.com（www 301 到裸域），会员体系迁到了
Cloudflare Worker：initium-member-api-prod.initium.workers.dev
（/health 返回 200，路由是活的）。但具体路径猜不出来，八个候选全 404。

【怎么用】

1. 打开端传媒 App，点一篇要会员的文章，往下划几下
2. Safari 打开 https://theinitium.com/__probe_log
3. 把页面内容发出来

这个脚本只记录、不改任何响应。

[rewrite_local]
^https:\/\/theinitium\.com\/__probe_log url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/dcm.probe.js
^https:\/\/theinitium\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/dcm.probe.js
^https:\/\/app\.theinitium\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/dcm.probe.js
^https:\/\/initium-member-api-prod\.initium\.workers\.dev\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/dcm.probe.js

[mitm]
hostname = theinitium.com, app.theinitium.com, initium-member-api-prod.initium.workers.dev

***********************************/

var url = $request.url || '';
var body = $response.body;

// ===================== 记录 =====================

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
    var ct = pick(h, 'content-type');
    if (ct) {
        p.push('ct=' + String(ct).split(';')[0]);
    }
    p.push('ce=' + (pick(h, 'content-encoding') || '-'));
    return p.join(' ');
}

function pick(h, name) {
    for (var k in h) {
        if (k.toLowerCase() === name) {
            return h[k];
        }
    }
    return '';
}

function record() {
    if (!shouldRecord(url)) {
        return;
    }
    var m = /^https?:\/\/([^\/?#]+)(\/[^?#]*)?/.exec(url);
    if (!m) {
        return;
    }
    var op = (url.match(/[?&]operationName=([^&]+)/) || [])[1];
    var key = m[1] + (m[2] || '/') + (op ? '  op=' + op : '');
    var line = key + '  [body=' + (body ? body.length : 0) + ']  ' + meta();

    var raw = prefsGet('dcm.hits') || '';
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
    if (lines.length > 80) {
        lines = lines.slice(lines.length - 80);
    }
    prefsSet('dcm.hits', lines.join('\n'));

    // 顺手把看起来跟会员有关的响应的开头留一份
    if (body && body.length < 4000 && /subscri|member|premium|paywall|entitle|verify|login|user/i.test(key + ' ' + body.slice(0, 300))) {
        prefsSet('dcm.sample', key + '\n\n' + body.slice(0, 1200));
    }
}

// ===================== 报告 =====================

function dumpLog() {
    prefsSet('dcm.ping', 'ping-' + new Date().getTime());
    var ping = prefsGet('dcm.ping');
    var storeOk = !!ping && ping.indexOf('ping-') === 0;

    var hits = prefsGet('dcm.hits') || '';
    var sample = prefsGet('dcm.sample') || '';

    var out = [];
    out.push('# 存储自检: ' + (storeOk ? 'OK' : '不可用 —— 报告为空不代表没有请求'));
    out.push('# 时间: ' + new Date().toISOString());
    out.push('');
    out.push('=== 端传媒 App 发出的请求 ===');
    if (hits) {
        out.push(hits);
    } else {
        out.push('(一条都没有)');
        out.push('  · 先在 App 里点开一篇要会员的文章');
        out.push('  · 检查 QX 的 [mitm] hostname 里有没有 theinitium.com');
        out.push('  · 检查重写资源是否已更新');
    }
    out.push('');
    out.push('=== 疑似会员相关的响应样本 ===');
    out.push(sample || '(没有命中关键词的响应)');

    $done({
        body: out.join('\n'),
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

if (url.indexOf('/__probe_log') >= 0) {
    dumpLog();
} else {
    record();
    $done({});
}
