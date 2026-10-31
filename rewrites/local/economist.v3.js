/***********************************

The Economist 解锁（Rules Hub 自托管版）

【App 有两条链路】

经济学人 App 的正文不来自 www.economist.com，而是移动端 GraphQL 网关：

    GET https://api.economist.com/teg/content/b2c-mobile/cp2-gateway/graphql
        ?operationName=ArticleQuery&variables=...

裸请求返回 401 Invalid credentials（前面是 Kong 网关，路由真实存在），
说明这是 App 专属接口，网页版完全不经过它。只把 www.economist.com
放进 [mitm] 是拦不到 App 的——列表能刷出来，点进去照样弹订阅墙。

启动时还会拉一个机构订阅标记：

    GET https://www.economist.com/api/bulk-subscriber
    -> {"isBulkSubscriber":false,"meta":{"client_ip":"x.x.x.x"}}

【三个自检地址，都不用抓包】

1) https://www.economist.com/api/bulk-subscriber
   看到 "isBulkSubscriber":true -> 证书、MITM、重写三件套都正常。

2) https://api.economist.com/__mitm_test
   看到 "MITM OK" -> api.economist.com 这条链路是通的（证书已覆盖这个域名）。
   看到 {"message":"no Route matched..."} -> 没被解密，MITM 名单里缺它。

3) https://www.economist.com/api/bulk-subscriber?log=1
   返回探针报告：命中了哪些请求、以及最近一次 GraphQL 响应的字段结构。

【本版为什么放宽了匹配】

上一版只匹配 cp2-gateway/graphql 一条路径，结果一条都没命中——说明
App 的正文可能走了别的路径，甚至根本不是这个域名。所以这版把
api.economist.com 和 www.economist.com 整个域都接管，先记录再说。
记录只多花几毫秒，确认链路后再收窄。

【文件名为什么带版本号】

QX 对远程脚本按 URL 缓存。只改内容、不改文件名时，就算在 QX 里点了
「更新资源」，拿到的还是旧脚本本体——线上改了等于没改，而且不报错。
所以每次改逻辑都要换文件名（v3 -> v4 ...），这是唯一可靠的强制刷新手段。

[rewrite_local]
^https:\/\/www\.economist\.com\/api\/bulk-subscriber url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v3.js
^https:\/\/api\.economist\.com\/teg\/content\/b2c-mobile\/cp2-gateway\/graphql url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v3.js
^https:\/\/www\.economist\.com\/[a-z-]+\/[0-9]{4}\/[0-9]{2}\/[0-9]{2}\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v3.js
^https:\/\/www\.economist\.com\/interactive\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v3.js
^https:\/\/api\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v3.js
^https:\/\/www\.economist\.com\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v3.js

[mitm]
hostname = www.economist.com, api.economist.com

***********************************/

var url = $request.url || '';
var body = $response.body;

// ===================== 分支一：App 的 GraphQL 正文接口 =====================

function handleGraphQL() {
    var obj;
    try {
        obj = JSON.parse(body);
    } catch (e) {
        console.log('Economist: GraphQL 响应不是 JSON，原样放行');
        $done({});
        return;
    }

    var op = (url.match(/[?&]operationName=([^&]+)/) || [])[1] || 'unknown';
    var changed = [];
    var report = [];

    scan(obj, 'root', report, changed, 0);

    var out = [];
    out.push('# operationName = ' + decodeURIComponent(op));
    out.push('# 原始响应 ' + body.length + ' 字节，记录于 ' + new Date().toISOString());
    out.push('# 改动 ' + changed.length + ' 处');
    for (var i = 0; i < changed.length && i < 40; i++) {
        out.push('  ' + changed[i]);
    }
    out.push('');
    out.push('# 响应结构');
    out = out.concat(report.slice(0, 300));

    prefsSet('econ.probe', out.join('\n'));

    if (changed.length > 0) {
        $done({ body: JSON.stringify(obj) });
    } else {
        $done({});
    }
}

// 递归遍历，顺便把结构记进 report
function scan(node, path, report, changed, depth) {
    if (!node || typeof node !== 'object' || depth > 14 || report.length > 320) {
        return;
    }

    if (Object.prototype.toString.call(node) === '[object Array]') {
        var n = node.length;
        var lim = Math.min(n, 2);
        for (var i = 0; i < lim; i++) {
            scan(node[i], path + '[' + i + ']', report, changed, depth + 1);
        }
        if (n > lim) {
            report.push(path + '[] 共 ' + n + ' 项（只展开前 ' + lim + ' 项）');
        }
        return;
    }

    for (var k in node) {
        if (!Object.prototype.hasOwnProperty.call(node, k)) {
            continue;
        }
        var v = node[k];
        var p = path + '.' + k;
        var kind = flagKind(k);

        if (kind && typeof v === 'boolean') {
            var want = (kind === 't');
            if (v !== want) {
                node[k] = want;
                changed.push(p + '  ' + v + ' -> ' + want);
            } else {
                report.push(p + ' = ' + v + '（已是目标值）');
            }
            continue;
        }

        if (v === null) {
            report.push(p + ' = null');
        } else if (typeof v === 'object') {
            scan(v, p, report, changed, depth + 1);
        } else if (typeof v === 'string') {
            report.push(p + ' = "' + shortStr(v) + '"  [' + v.length + ' 字符]');
        } else {
            report.push(p + ' = ' + String(v));
        }
    }
}

// 字段名 -> 目标值。去掉下划线和大小写后比对，兼容 is_premium / isPremium。
var FLAG_FALSE = toSet('isPremium,isPaid,isLocked,isPaywalled,paywalled,' +
    'requiresSubscription,requiresPayment,isGated,gated,isRestricted,restricted,' +
    'isSubscriberOnly,subscriberOnly,isPremiumContent,hasPaywall,isPaywall,' +
    'showPaywall,paywallEnabled,isRegistrationRequired,registrationRequired,' +
    'needsSubscription,isMetered,metered,isBlocked');

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

// 长字符串只留首尾，否则正文会把报告撑爆
function shortStr(s) {
    var t = String(s).replace(/\s+/g, ' ');
    if (t.length <= 120) {
        return t;
    }
    return t.slice(0, 80) + ' … ' + t.slice(-40);
}

// ===================== 分支二：机构订阅标记 =====================

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

// ===================== 分支三：网页正文 =====================

function handleHtml() {
    var trimmed = String(body).replace(/^\s+/, '');
    if (trimmed.charAt(0) !== '<') {
        // JSON / JS / CSS / 图片之类的，一律别动
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

// 按 id 摘掉一个 div，靠配对计数找闭合标签，避免正则贪婪吃多
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

// 解除滚动锁（注册墙生效时 body 常被加上 overflow:hidden）
function unlockScroll(html) {
    return html.replace(/<body([^>]*?)(\s+style=)(["'])([^"']*)\3/gi,
        function (all, pre, eq, q, css) {
            var cleaned = css.replace(/overflow(-y)?\s*:\s*hidden\s*;?/gi, '').trim();
            return cleaned ? '<body' + pre + eq + q + cleaned + q : '<body' + pre;
        });
}

// ===================== 探针 =====================

// 只记非静态资源，否则一次开屏就刷出几十条图片记录
function shouldRecord(u) {
    if (/\.(?:js|css|png|jpe?g|gif|svg|woff2?|ttf|eot|ico|webp|avif|mp4|m3u8|map)(?:[?#]|$)/i.test(u)) {
        return false;
    }
    return true;
}

function record(u, size) {
    if (!shouldRecord(u)) {
        return;
    }
    var m = /^https?:\/\/([^\/?#]+)(\/[^?#]*)?/.exec(u);
    if (!m) {
        return;
    }
    // 按「域名 + 路径 + operationName」去重。只按路径去重的话，
    // ArticleQuery / FindHomepage 这些会互相覆盖，只剩最后一条。
    var op = (u.match(/[?&]operationName=([^&]+)/) || [])[1];
    var key = m[1] + (m[2] || '/') + (op ? '  op=' + op : '');
    var line = key + '  [' + size + ']';

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
    if (lines.length > 80) {
        lines = lines.slice(lines.length - 80);
    }
    prefsSet('econ.hits', lines.join('\n'));
}

function dumpProbe() {
    // 存储自检：先写后读。能分清「真的一条请求都没有」和「$prefs 不可用」——
    // 否则报告为空时根本判断不了是哪种，白猜一轮。
    prefsSet('econ.ping', 'ping-' + new Date().getTime());
    var ping = prefsGet('econ.ping');
    var storeOk = !!ping && ping.indexOf('ping-') === 0;

    var hits = prefsGet('econ.hits') || '';
    var probe = prefsGet('econ.probe') || '';

    var out = [];
    out.push('# 存储自检: ' + (storeOk ? 'OK (' + ping + ')' : '不可用 —— 报告为空不代表没有请求'));
    out.push('# 报告时间: ' + new Date().toISOString());
    out.push('');
    out.push('=== 命中的请求（最多 80 条，按域名+路径去重）===');
    if (hits) {
        out.push(hits);
    } else {
        out.push('(一条都没有)');
        out.push('  说明这两个域名的请求根本没走到本脚本。可能是：');
        out.push('  · QX 的 [mitm] hostname 里缺 www.economist.com / api.economist.com');
        out.push('  · 重写资源没更新，设备上还是旧脚本');
        out.push('  · App 还没产生请求（先在 App 里点开一篇文章）');
    }
    out.push('');
    out.push('=== 最近一次 GraphQL 响应结构 ===');
    out.push(probe || '(没有记录到，表示没有任何请求命中 cp2-gateway/graphql)');

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

// ===================== 执行入口 =====================
// 必须放在文件末尾：函数声明会提升，但 FLAG_FALSE / FLAG_TRUE 这类
// var 赋值不会。写在前面的话，第一次调用 flagKind 时字段表还是 undefined，
// 整个脚本会静默抛异常、QX 拿不到 $done，表现为 App 一直转圈。

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
} else if (!body) {
    record(url, 0);
    $done({});
} else {
    record(url, body.length);
    handleHtml();
}
