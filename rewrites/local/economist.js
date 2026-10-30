/***********************************

The Economist 付费墙处理（Rules Hub 自托管版）

背景：经济学人没有公开的 Quantumult X 解锁脚本。GitHub 全量搜过，
唯一叫「经济学人」的是 chxm1023 的 jjxrsl.js，但那款针对的是
「经济学人·商论」（api.hummingbird.businessreview.global），
而这个域名现在连 DNS 都解析不出来了 —— 服务已经整体下线，无从恢复。

所以这份是按 Bypass Paywalls Clean 4.4.7.6 的实现重写的：
  1. 订阅墙由 Zephr 驱动，入口是 /zephr/feature
  2. 前端遮罩由 /latest/wall-ui.js 渲染，节点是 div#tp-regwall
把这两者拦掉，注册墙就不会生成；服务端已经渲染进 HTML 的那部分，
由本脚本摘掉，并解除 body 的滚动锁。

只对网页版（Safari）有效。App 内的订阅校验走的是另一套 API，
没抓包无法确定字段，不在本脚本范围内。

自托管原因：上游脚本普遍指向个人仓库，删库即静默失效
（QX 拉不到脚本不报错，只是重写不再生效）。

[rewrite_local]
^https:\/\/www\.economist\.com\/zephr\/feature url reject
^https:\/\/[a-z0-9-]+\.economist\.com\/latest\/wall-ui\.js url reject
^https:\/\/www\.economist\.com\/[a-z-]+\/[0-9]{4}\/[0-9]{2}\/[0-9]{2}\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js
^https:\/\/www\.economist\.com\/interactive\/ url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/economist.js

[mitm]
hostname = www.economist.com

***********************************/

var REGWALL_IDS = ['tp-regwall'];

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

var body = $response.body;
if (!body) {
    $done({});
} else {
    try {
        var out = body;
        for (var k = 0; k < REGWALL_IDS.length; k++) {
            out = stripDivById(out, REGWALL_IDS[k]);
        }
        out = unlockScroll(out);
        // 兜底：万一 reject 没命中，把墙脚本的标签也去掉
        out = out.replace(/<script\b[^>]*(?:wall-ui\.js|\/zephr\/)[^>]*>\s*<\/script>/gi, '');
        $done({ body: out });
    } catch (e) {
        console.log('Economist rewrite 出错，原样放行 -> ' + e);
        $done({});
    }
}
