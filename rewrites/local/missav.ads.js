/***********************************

MissAV 去广告（Rules Hub 本地维护版）

上游 ddgksf2013 的版本停在 2025.12，站点的广告位已经换了一轮：
现在首页/列表页的广告主要是 go.mayzaent.com 与 t.rallytrck.website 的 iframe，
以及包在 playerThumbWrapper 里的 go.greentrafsa.com 推广卡片 —— 上游的
CSS 选择器一个都没覆盖到，所以「规则在跑但广告还在」。

本文件由 Rules Hub 自己维护，改动记在 docs/ROUTER_STATE.local.md 的变更记录里。

[rewrite_local]

^https?:\/\/missav\.(ws|live|com|ai)\/(?!(.*(api|login|cdn-cgi|verify|auth|captch|(\.(js|css|jpg|jpeg|png|webp|gif|zip|woff|woff2|m3u8|mp4|mov|m4v|avi|mkv|flv|rmvb|wmv|rm|asf|asx|mp3|json|ico|otf|ttf))))) url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/missav.ads.js

***********************************/

const AD_HOSTS = ["mayzaent", "greentrafsa", "rallytrck"];

// 上游保留的选择器 + 本站实测新增的广告位
const CSS = `
a[href^='https://theporndude.com'],
a[href*='mycomic'],
a[href*='myavlive'],
a[href*='bit.ly'],
a[target=_blank][href*='bit.ly'],
a[href*='/vip'],
a[href*='greentrafsa'],
a[href*='mayzaent'],
img[src*='.gif'],
iframe[src*='ads'],
iframe[src*='mayzaent'],
iframe[src*='rallytrck'],
iframe[src*='greentrafsa'],
div[style*='z-index: 1001'],
div[style='width: 300px; height: 250px;'],
ul.space-y-2.mb-4.ml-4.list-disc.text-nord14,
div.space-y-5.mb-5,
div.under_player,
div.fixed.right-2.bottom-2,
div.playerThumbWrapper--bcYD7:has(a[href*='greentrafsa']) {
    display: none !important;
    pointer-events: none !important;
}
body { overflow-x: hidden !important; }
`;

const BLOCK_POPUP = `<script>(function(){
  var raw = window.open;
  window.open = function(){ try { return null; } catch (e) { return raw.apply(window, arguments); } };
})();</script>`;

let body = $response.body || "";

// 1. 直接摘掉广告的 script / iframe 标签，比事后隐藏更干净
const hostAlt = AD_HOSTS.join("|");
body = body.replace(
  new RegExp('<script[^>]*src="[^"]*(?:' + hostAlt + ')[^"]*"[^>]*>\\s*</script>', "gi"), ""
);
body = body.replace(
  new RegExp('<iframe[^>]*src="[^"]*(?:' + hostAlt + ')[^"]*"[^>]*>\\s*</iframe>', "gi"), ""
);

// 2. 注入 CSS 与弹窗拦截
const inject = "<style>" + CSS + "</style>" + BLOCK_POPUP;
if (body.indexOf("</head>") !== -1) {
  body = body.replace("</head>", inject + "</head>");
} else {
  body = inject + body;
}

$done({ body: body });
