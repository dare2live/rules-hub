/***********************************

The Economist 解锁（Rules Hub 自托管版）

【现状：App 原生阅读器无解，改走 WebView】

三轮抓包已经确认，App 的拦截不在网络层：

1. 正文完整下发。wordCount 1974 的文章拿到 12146 字，比例 6.0，
   和英文「每词约 6 字符」对得上，服务端没扣内容。
2. 响应里没有任何付费墙字段。按 premium / subscri / paywall / access /
   entitle / locked / restrict / tier / member / gated / abridg / truncat /
   preview / free 扫全树，零命中。
3. App 也不问账户。login / id / my.economist.com 三个域名挂上 MITM 后，
   一条请求都没出现。

内容不缺、标记没有、账户不问——判定发生在 App 本地，网络层没有可改的东西。

【所以这版改走 WebView】

文章响应里有个 contentIdentity.forceAppWebView 字段（默认 false），
服务端用它把特定文章丢进 WebView 打开。把它翻成 true，App 就会用网页
渲染文章，而网页这条路我们是能动的：

    /api/bulk-subscriber -> isBulkSubscriber: true
    文章页 HTML          -> 摘掉 Zephr 注册墙 div#tp-regwall + 解滚动锁

【自检】

    https://www.economist.com/api/bulk-subscriber
        看到 "isBulkSubscriber":true  -> 证书、MITM、重写三件套正常
    https://www.economist.com/api/bulk-subscriber?log=1
        看上一轮实际改了几处、改了哪些

【文件名为什么带版本号】

QX 对远程脚本按 URL 缓存。只改内容、不改文件名时，就算在 QX 里点了
「更新资源」，拿到的还是旧脚本本体——线上改了等于没改，而且不报错。

[rewrite_local]
^https:\/\/www\.economist\.com\/api\/bulk-subscriber url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v7.js
^https:\/\/api\.economist\.com\/teg\/content\/b2c-mobile\/cp2-gateway\/graphql url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v7.js
^https:\/\/www\.economist\.com\/[a-z-]+\/[0-9]{4}\/[0-9]{2}\/[0-9]{2}\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v7.js
^https:\/\/www\.economist\.com\/interactive\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.v7.js

[mitm]
hostname = www.economist.com, api.economist.com

***********************************/

var url = $request.url || '';
var body = $response.body;

// ===================== GraphQL 正文接口 =====================

function handleGraphQL() {
    var obj;
    try {
        obj = JSON.parse(body);
    } catch (e) {
        console.log('Economist: GraphQL 响应不是 JSON，原样放行');
        $done({});
        return;
    }

    var changed = [];
    walk(obj, 'root', changed, 0);

    if (changed.length > 0) {
        prefsSet('econ.last', new Date().toISOString() + '  改动 ' + changed.length + ' 处\n' +
            changed.slice(0, 30).join('\n'));
        $done({ body: JSON.stringify(obj) });
    } else {
        $done({});
    }
}

function walk(node, path, changed, depth) {
    if (!node || typeof node !== 'object' || depth > 16) {
        return;
    }
    if (Object.prototype.toString.call(node) === '[object Array]') {
        for (var i = 0; i < node.length; i++) {
            walk(node[i], path + '[' + i + ']', changed, depth + 1);
        }
        return;
    }
    for (var k in node) {
        if (!Object.prototype.hasOwnProperty.call(node, k)) {
            continue;
        }
        var v = node[k];
        var kind = flagKind(k);
        if (kind && typeof v === 'boolean') {
            var want = (kind === 't');
            if (v !== want) {
                node[k] = want;
                if (changed.length < 200) {
                    changed.push(path + '.' + k + '  ' + v + ' -> ' + want);
                }
            }
            continue;
        }
        if (v && typeof v === 'object') {
            walk(v, path + '.' + k, changed, depth + 1);
        }
    }
}

// 字段名 -> 目标值。去掉下划线和大小写后比对，兼容 is_premium / isPremium。
var FLAG_FALSE = toSet('isPremium,isPaid,isLocked,isPaywalled,paywalled,' +
    'requiresSubscription,requiresPayment,isGated,gated,isRestricted,restricted,' +
    'isSubscriberOnly,subscriberOnly,subscriberContent,isPremiumContent,' +
    'hasPaywall,isPaywall,showPaywall,paywallEnabled,isRegistrationRequired,' +
    'registrationRequired,needsSubscription,isMetered,metered,isBlocked');

// forceAppWebView 放这里是本版的关键：把原生阅读器换成 WebView，
// 网页那条路我们才有办法。subscriberContent 管的是会员专享播客。
var FLAG_TRUE = toSet('isSubscriber,isEntitled,entitled,hasAccess,hasSubscription,' +
    'hasFullAccess,canRead,isAccessibleForFree,isAccessible,isUnlocked,unlocked,' +
    'isFree,isFreeArticle,isBulkSubscriber,forceAppWebView');

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

// ===================== 自检 =====================

function dumpLast() {
    var last = prefsGet('econ.last');
    $done({
        body: last
            ? '=== 上一轮改写 ===\n' + last
            : '(还没有记录到改写。先在 App 里点开一篇文章，再回到这里刷新。)',
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
    dumpLast();
} else if (url.indexOf('cp2-gateway/graphql') >= 0) {
    if (body) {
        handleGraphQL();
    } else {
        $done({});
    }
} else if (url.indexOf('/api/bulk-subscriber') >= 0) {
    if (body) {
        handleBulk();
    } else {
        $done({});
    }
} else if (!body) {
    $done({});
} else {
    handleHtml();
}
