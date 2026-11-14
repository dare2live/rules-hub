/***********************************

> 应用名称：MissAV 去广告（Rules Hub 本地维护版 v5）
> 更新时间：2026-11-09
> 架构说明：
  1. 严格 Cloudflare 验证页护栏：兼容 QX ($response.status) 与 Clash ($response.statusCode)，
     凡 403/503 或含 _cf_chl_opt / challenges.cloudflare.com 的响应一律原样放行，绝不触发验证死循环；
  2. 将 HTML 内联广告 script/iframe 替换为隐藏标记节点 <i data-ad-marker="1">，保留外层浮窗结构特征；
  3. 增强 CSS 选择器：覆盖所有 fixed + bottom-* + right-* 组合、内联 position:fixed 及含关闭按钮/SVG/iframe/ins 的右下角透明浮窗；
  4. 轻量级安全 DOM 清理：仅针对尺寸 <=450px 且不含 video/nav/header/input/form/.plyr 的右下角 fixed 空壳浮窗进行定点移除，杜绝白屏。

[rewrite_local]

^https?:\/\/(www\.)?(missav|thisav)\.(ws|ai|live|com)\/(?!(.*(api|login|register|logout|cdn-cgi|verify|auth|captch|(\.(js|css|jpg|jpeg|png|webp|gif|zip|woff|woff2|m3u8|mp4|mov|m4v|avi|mkv|flv|rmvb|wmv|rm|asf|asx|mp3|json|ico|otf|ttf|svg|ts|vtt))))) url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/missav.clean.v5.js

[mitm]

hostname = missav.live, missav.ws, missav.ai, missav.com, www.missav.ws, www.missav.ai, www.missav.live, www.missav.com, thisav.com

***********************************/

let body = $response && $response.body;
const rawStatus = ($response && ($response.statusCode || $response.status)) || 200;
const statusStr = String(rawStatus);

if (
  !body ||
  rawStatus === 403 ||
  rawStatus === 503 ||
  statusStr.includes("403") ||
  statusStr.includes("503") ||
  body.includes("_cf_chl_opt") ||
  body.includes("challenges.cloudflare.com") ||
  body.includes("cf-browser-verification") ||
  !body.includes("</head>")
) {
  $done({});
} else {
  const AD_HOSTS = [
    "mayzaent",
    "greentrafsa",
    "rallytrck",
    "tsyndicate",
    "exoclick",
    "magsrv",
    "juicyads",
    "trafficjunky",
    "realsrv",
    "popads",
    "stripchat",
    "myavlive",
    "theporndude",
    "liquidfire"
  ];

  const hostAlt = AD_HOSTS.join("|");
  body = body.replace(
    new RegExp('<script[^>]*src=["\'][^"\']*(?:' + hostAlt + ')[^"\']*["\'][^>]*>\\s*<\\/script>', "gi"),
    '<i data-ad-marker="1" style="display:none !important"></i>'
  );
  body = body.replace(
    new RegExp('<iframe[^>]*src=["\'][^"\']*(?:' + hostAlt + ')[^"\']*["\'][^>]*>\\s*<\\/iframe>', "gi"),
    '<i data-ad-marker="1" style="display:none !important"></i>'
  );

  const cssAndScript = `<style type="text/css">
[data-ad-marker],
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
a[href*="bit.ly"],
iframe[src*="mayzaent"],
iframe[src*="rallytrck"],
iframe[src*="greentrafsa"],
iframe[src*="tsyndicate"],
iframe[src*="exoclick"],
iframe[src*="magsrv"],
iframe[src*="juicyads"],
iframe[src*="trafficjunky"],
iframe[src*="realsrv"],
ins.eas6a97888e,
ins[class*="eas"],
div.under_player,
div[class*="lg:block"],
ul.space-y-2.mb-4.ml-4.list-disc.text-nord14,
div.space-y-5.mb-5,
div[style*="z-index: 1001"],
div[style*="z-index: 9999"],
div[style*="width: 300px"][style*="height: 250px"],
div[style="width: 300px; height: 250px;"],
div[class*="fixed"][class*="bottom-"][class*="right-"]:not(:has(video, nav, header, main, input, form, .plyr)),
div[class*="fixed"][class*="bottom-"][class*="left-"]:not(:has(video, nav, header, main, input, form, .plyr)),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has([data-ad-marker]),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has(iframe),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has(ins),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has(a[target="_blank"]),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has([class*="close" i]),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has(button),
div[class*="fixed"]:not(:has(video, nav, header, main, input, form, .plyr)):has(svg),
div[style*="position: fixed"]:not(:has(video, nav, header, main, input, form, .plyr)),
div[style*="position:fixed"]:not(:has(video, nav, header, main, input, form, .plyr)),
[class*="adsbox" i],
[class*="adbox" i],
[class*="popup-ad" i],
[class*="ad-popup" i],
[class*="ad-modal" i],
[class*="ad-overlay" i] {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
}
</style><script type="text/javascript">(function(){
  var o = window.open;
  window.open = function(){ return null; };
  function isProtected(el) {
    if (!el || el.nodeType !== 1) return true;
    var tag = (el.tagName || '').toUpperCase();
    if (tag === 'HTML' || tag === 'BODY' || tag === 'MAIN' || tag === 'HEADER' || tag === 'NAV' || tag === 'FOOTER' || tag === 'ARTICLE') return true;
    var cls = typeof el.className === 'string' ? el.className : '';
    if (/\\b(min-h-screen|max-w-7xl|container)\\b/.test(cls)) return true;
    try {
      if (el.querySelector('main, nav, header, footer, video, form, input, .plyr, [id*="player"]')) return true;
    } catch (e) {}
    return false;
  }
  function cleanFloatingBox() {
    try {
      var nodes = document.querySelectorAll('div, aside, section, ins');
      var vh = window.innerHeight || 800;
      var vw = window.innerWidth || 400;
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (isProtected(el)) continue;
        var cls = typeof el.className === 'string' ? el.className : '';
        var cs = window.getComputedStyle ? window.getComputedStyle(el) : null;
        var isFixed = (cs && cs.position === 'fixed') || /\\bfixed\\b/.test(cls);
        if (!isFixed) continue;
        var rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
        var w = rect ? rect.width : (el.offsetWidth || 0);
        var h = rect ? rect.height : (el.offsetHeight || 0);
        var nearCorner = !rect || rect.bottom >= vh - 180 || rect.right >= vw - 180 || (cs && (cs.bottom !== 'auto' || cs.right !== 'auto'));
        if (w <= 460 && h <= 460 && nearCorner) {
          el.style.setProperty('display', 'none', 'important');
          el.style.setProperty('visibility', 'hidden', 'important');
          el.style.setProperty('pointer-events', 'none', 'important');
          el.remove();
        }
      }
    } catch (e) {}
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', cleanFloatingBox);
  } else {
    cleanFloatingBox();
  }
  setTimeout(cleanFloatingBox, 600);
  setTimeout(cleanFloatingBox, 1800);
  setTimeout(cleanFloatingBox, 3500);
})();</script></head>`;

  body = body.replace("</head>", cssAndScript);
  $done({ body });
}
