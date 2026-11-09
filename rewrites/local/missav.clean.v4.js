/***********************************

> 应用名称：MissAV 去广告（Rules Hub 本地维护版 v4）
> 更新时间：2026-11-09
> 架构说明：
  回归上游 @ddgksf2013 (V1.0.6) 的极简设计：
  1. 仅在 HTML 含 </head> 且非 Cloudflare 验证页（_cf_chl_opt / challenges.cloudflare.com）时注入；
  2. 纯 CSS 隐藏广告位与右下角固定浮窗（div.fixed.right-2.bottom-2 等）+ 6 行 window.open 拦截；
  3. 零 MutationObserver、零 DOM 遍历删除（杜绝误删主容器导致白屏，杜绝触发 CF Turnstile 完整性自检）；
  4. [mitm] 仅解密主域名（不写 *.missav.* 通配），确保 CF 验证子域与视频流 CDN 不受影响。

[rewrite_local]

^https?:\/\/(www\.)?(missav|thisav)\.(ws|ai|live|com)\/(?!(.*(api|login|register|logout|cdn-cgi|verify|auth|captch|(\.(js|css|jpg|jpeg|png|webp|gif|zip|woff|woff2|m3u8|mp4|mov|m4v|avi|mkv|flv|rmvb|wmv|rm|asf|asx|mp3|json|ico|otf|ttf|svg|ts|vtt))))) url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/missav.clean.v4.js

[mitm]

hostname = missav.live, missav.ws, missav.ai, missav.com, www.missav.ws, www.missav.ai, www.missav.live, www.missav.com, thisav.com

***********************************/

let body = $response && $response.body;

if (
  !body ||
  $response.status === 403 ||
  $response.status === 503 ||
  body.includes("_cf_chl_opt") ||
  body.includes("challenges.cloudflare.com") ||
  !body.includes("</head>")
) {
  $done({});
} else {
  const cssAndScript = `<style type="text/css">
a[href^="https://theporndude.com"],
a[href^="https://tsyndicate.com"],
a[href^="https://achtung.live"],
a[href^="https://s.zlink2.com"],
a[href^="https://s.zlinkd.com"],
a[href^="https://s.zlink3.com"],
a[href^="https://www.liquidfire.mobi"],
a[href^="https://myavlive.com"],
a[href^="https://stripchat.com"],
a[href*="mycomic"],
a[href*="myavlive"],
a[href*="greentrafsa"],
a[href*="mayzaent"],
a[href*="rallytrck"],
a[href*="tsyndicate"],
a[href*="exoclick"],
a[href*="magsrv"],
a[href*="juicyads"],
a[href*="trafficjunky"],
a[href*="realsrv"],
iframe[src*="mayzaent"],
iframe[src*="rallytrck"],
iframe[src*="greentrafsa"],
iframe[src*="tsyndicate"],
iframe[src*="exoclick"],
iframe[src*="magsrv"],
iframe[src*="juicyads"],
iframe[src*="trafficjunky"],
ins.eas6a97888e,
ins[class*="eas"],
div.under_player,
div.fixed.right-2.bottom-2,
div.fixed.bottom-2.right-2,
div.fixed.right-4.bottom-4,
div.fixed.bottom-4.right-4,
div.fixed.right-0.bottom-0,
div.fixed.bottom-0.right-0,
div[class*="lg:block"],
ul.space-y-2.mb-4.ml-4.list-disc.text-nord14,
div.space-y-5.mb-5,
div[style*="z-index: 1001"],
div[style="width: 300px; height: 250px;"] {
    display: none !important;
    pointer-events: none !important;
}
</style><script type="text/javascript">(function(){const o=window.open;window.open=function(){return null;};})();</script></head>`;

  body = body.replace("</head>", cssAndScript);
  $done({ body });
}
