/***********************************

The Economist 解锁（Rules Hub 自托管版）

【为什么只拦 www 不够】

经济学人 App 的正文不来自 www.economist.com，而是移动端 GraphQL 网关：

    GET https://api.economist.com/teg/content/b2c-mobile/cp2-gateway/graphql
        ?operationName=ArticleQuery&variables=...

裸请求返回 401 Invalid credentials（前面是 Kong 网关，路由真实存在），
说明这是 App 专属接口，网页版完全不经过它。所以只把 www.economist.com
放进 [mitm] 是拦不到 App 的——文章列表能刷出来，点进去照样弹订阅墙。

另外 App 启动时还会拉一个机构订阅标记：

    GET https://www.economist.com/api/bulk-subscriber
    -> {"isBulkSubscriber":false,"meta":{"client_ip":"x.x.x.x"}}

两条链路都改成「已订阅」才进得了正文。

【自检 —— 不需要抓包工具】

1. Safari 打开 https://www.economist.com/api/bulk-subscriber
   看到 "isBulkSubscriber":true，说明证书、MITM、重写三件套都正常。
2. 如果 App 里点开文章还是弹墙，Safari 打开
   https://www.economist.com/api/bulk-subscriber?log=1
   会返回最近一次 GraphQL 响应的结构摘要（字段名、类型、长度、首尾片段）。
   把这个贴出来就能定位到底卡在哪个字段。

【网页版 —— 附带】

经济学人网页的注册墙由 Zephr 驱动，前端遮罩是 div#tp-regwall。
脚本会把它从 HTML 里摘掉并解除 body 的 overflow:hidden。
这部分不影响 App；不想用可以只删 rewrite_local 里的文章行。

【为什么自托管】

上游没有公开的 QX 版本。已知的唯一实现是 KeiKinn/Surge_Script 的
Paywall.sgmodule，走 Surge 的 Map Local 挂一个本地 JSON（2020 年的文件，
内容就是 {"meta":{},"isBulkSubscriber":true}）。QX 没有 Map Local，
所以改成 response-body 脚本，逻辑等价且能保留原始 meta。

[rewrite_local]
^https:\/\/www\.economist\.com\/api\/bulk-subscriber url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js
^https:\/\/api\.economist\.com\/teg\/content\/b2c-mobile\/cp2-gateway\/graphql url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js
^https:\/\/www\.economist\.com\/[a-z-]+\/[0-9]{4}\/[0-9]{2}\/[0-9]{2}\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js
^https:\/\/www\.economist\.com\/interactive\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js

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
        // 一个字段都没动，就不要白白重排一遍 body
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
    var trimmed = body.replace(/^\s+/, '');
    if (trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[') {
        $done({});
        return;
    }
    try {
        var out = stripDivById(body, 'tp-regwall');
        out = unlockScroll(out);
        $done({ body: out });
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

function dumpProbe() {
    var text = '';
    try {
        if (typeof $prefs !== 'undefined' && $prefs.valueForKey) {
            text = $prefs.valueForKey('econ.probe') || '';
        }
    } catch (e) {}
    if (!text) {
        text = '(还没有记录到 GraphQL 响应)\n\n' +
            '请先在 App 里点开一篇文章，再回到这里刷新。\n' +
            '如果一直为空，说明 api.economist.com 没有被 MITM——' +
            '检查 QX 的 [mitm] hostname 里有没有这个域名，以及证书是否已信任。';
    }
    $done({
        body: text,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
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

if (!body) {
    $done({});
} else if (/[?&]log=1(?:&|$)/.test(url)) {
    dumpProbe();
} else if (url.indexOf('cp2-gateway/graphql') >= 0) {
    handleGraphQL();
} else if (url.indexOf('/api/bulk-subscriber') >= 0) {
    handleBulk();
} else {
    handleHtml();
}
