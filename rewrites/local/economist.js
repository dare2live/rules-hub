/***********************************

The Economist 解锁（Rules Hub 自托管版）

【App 解锁 —— 主用途】
经济学人 iOS App 启动时会拉一个机构订阅标记：

    GET https://www.economist.com/api/bulk-subscriber
    -> {"isBulkSubscriber":false,"meta":{"client_ip":"x.x.x.x"}}

App 拿 isBulkSubscriber 决定要不要弹订阅墙。本脚本把它改成 true，
并保留原始 meta（里面的 client_ip 是真实返回值，去掉反而不自然）。

这个端点 2026-10-30 实测仍是 HTTP 200、字段名没变，只是值为 false。

【网页版 —— 附带】
经济学人网页的注册墙由 Zephr 驱动，前端遮罩是 div#tp-regwall。
脚本会把它从 HTML 里摘掉并解除 body 的 overflow:hidden。
这部分是附带的，不影响 App；不想用可以只删 rewrite_local 里的文章行。

【为什么自托管】
上游没有公开的 QX 版本。已知的唯一实现是 KeiKinn/Surge_Script 的
Paywall.sgmodule，走 Surge 的 Map Local 挂一个本地 JSON（2020 年的文件，
内容就是 {"meta":{},"isBulkSubscriber":true}）。QX 没有 Map Local，
所以改成 response-body 脚本，逻辑等价且能保留原始 meta。

[rewrite_local]
^https:\/\/www\.economist\.com\/api\/bulk-subscriber url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js
^https:\/\/www\.economist\.com\/[a-z-]+\/[0-9]{4}\/[0-9]{2}\/[0-9]{2}\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js
^https:\/\/www\.economist\.com\/interactive\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js

[mitm]
hostname = www.economist.com

***********************************/

var body = $response.body;

if (!body) {
    $done({});
} else {
    var trimmed = body.replace(/^\s+/, '');
    var isJson = trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[';

    if (isJson) {
        // ===== App：机构订阅标记 =====
        try {
            var obj = JSON.parse(body);
            if (obj && typeof obj === 'object' && 'isBulkSubscriber' in obj) {
                obj.isBulkSubscriber = true;
                if (!obj.meta || typeof obj.meta !== 'object') {
                    obj.meta = {};
                }
                $done({ body: JSON.stringify(obj) });
            } else {
                // 不是订阅标记，别的 JSON 接口一律不碰
                $done({});
            }
        } catch (e) {
            console.log('Economist: JSON 解析失败，原样放行 -> ' + e);
            $done({});
        }
    } else {
        // ===== 网页：摘注册墙 + 解滚动锁 =====
        try {
            var out = stripDivById(body, 'tp-regwall');
            out = unlockScroll(out);
            $done({ body: out });
        } catch (e) {
            console.log('Economist: HTML 处理失败，原样放行 -> ' + e);
            $done({});
        }
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
