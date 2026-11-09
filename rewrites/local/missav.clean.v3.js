/***********************************

MissAV 去广告（Rules Hub 本地维护版 v3）

上游 ddgksf2013 的版本停在 2025.12，站点的广告位已经换了一轮。
本文件由 Rules Hub 自己维护。

改名说明（重要）：
  QX 按 URL 缓存远程脚本本体，只改内容、不改文件名时设备不会重新下载，
  线上改了等于没改，而且不报错。所以每次改脚本都要换文件名 ——
  文件名本身就是缓存键。

v3 修复的问题（2026-11-09）：
  1. 修复「主页一闪而过然后白屏」：
     v2 的 sweep(document) 遍历页面所有 div，并用 AD_RE.test(el.innerHTML) 判断。
     由于页脚/推荐区含有 theporndude 等链接，最外层根容器 div.min-h-screen 的
     innerHTML 必然命中正则，导致 DOMContentLoaded 时整页根 div 被 remove() 删空。
     v3 为 isAdLayer 增加严格结构护栏：绝不触碰含 main/nav/header/footer/video/player
     的祖先容器或大尺寸布局节点，只清理独立的广告浮层与叶子容器。
  2. 修复「首页漂浮广告内容被过滤但空窗口和关闭按钮还在」：
     v2 先用正则把 <iframe src="...mayzaent..."> 替换为空串，导致外层 fixed 浮层
     失去 iframe 特征，CSS :has(iframe) 和 JS 均无法识别剩下的空壳容器。
     v3 将广告 script/iframe 替换为 <i data-ad-marker="1"></i> 标记节点，
     使 CSS div[class*='fixed']:has([data-ad-marker]) 在首屏渲染瞬间即隐藏整个浮层，
     并由运行时脚本彻底移除该 fixed 容器（含 SVG 关闭按钮浮层）。

[rewrite_local]

^https?:\/\/(www\.)?missav\.(ws|live|com|ai)\/(?!(.*(api|login|register|logout|cdn-cgi|verify|auth|captch|(\.(js|css|jpg|jpeg|png|webp|gif|zip|woff|woff2|m3u8|mp4|mov|m4v|avi|mkv|flv|rmvb|wmv|rm|asf|asx|mp3|json|ico|otf|ttf|svg|ts|vtt))))) url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/missav.clean.v3.js

[mitm]

hostname = missav.ws, *.missav.ws, missav.ai, *.missav.ai, missav.live, *.missav.live, missav.com, *.missav.com

***********************************/

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
  "popads"
];

// 已知广告位。类名用子串匹配，站点改版换 Tailwind 类名也能命中。
const CSS = `
[data-ad-marker],
a[href^='https://theporndude.com'],
a[href*='mycomic'],
a[href*='myavlive'],
a[href*='bit.ly'],
a[href*='/vip'],
a[href*='greentrafsa'],
a[href*='mayzaent'],
a[href*='rallytrck'],
a[href*='tsyndicate'],
a[href*='exoclick'],
a[href*='magsrv'],
a[href*='juicyads'],
a[href*='trafficjunky'],
a[href*='realsrv'],
img[src*='.gif'],
iframe[src*='ads'],
iframe[src*='mayzaent'],
iframe[src*='rallytrck'],
iframe[src*='greentrafsa'],
iframe[src*='tsyndicate'],
iframe[src*='exoclick'],
iframe[src*='magsrv'],
iframe[src*='juicyads'],
iframe[src*='trafficjunky'],
ins.eas6a97888e,
ins[class*='eas'],
div[style*='z-index: 1001'],
div[style*='z-index: 9999'],
div[style='width: 300px; height: 250px;'],
div[style*='width: 300px'][style*='height: 250px'],
ul.space-y-2.mb-4.ml-4.list-disc.text-nord14,
div.space-y-5.mb-5,
div.under_player,
div.playerThumbWrapper--bcYD7:has(a[href*='greentrafsa']),

/* 漂浮广告容器：fixed 定位且内含广告标记、iframe、ins 或广告链接，整块隐藏。
   明确排除含 video / nav / header 的正常页面组件。 */
div[class*='fixed']:not(:has(video, nav, header, input, form)):has([data-ad-marker]),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='mayzaent']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='greentrafsa']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='rallytrck']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='tsyndicate']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='exoclick']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='magsrv']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(a[href*='bit.ly']),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(iframe),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has(ins),
div[class*='fixed']:not(:has(video, nav, header, input, form)):has([class*='close' i]),
div.fixed.bottom-0.right-0:not(:has(video, nav, input)),
div.fixed.bottom-2.right-2:not(:has(video, nav, input)),
div.fixed.bottom-4.right-4:not(:has(video, nav, input)),
/* 广告遮罩与弹窗（按类名子串） */
[class*='adsbox' i],
[class*='adbox' i],
[class*='popup-ad' i],
[class*='ad-popup' i],
[class*='ad-modal' i],
[class*='ad-overlay' i] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
}
`;

// 运行时清理：只清理独立的 fixed 漂浮广告盒与含 data-ad-marker 的小容器，绝不触碰页面主干结构。
const BLOCK_POPUP = `<script>(function(){
  var AD_SEL = '[data-ad-marker], iframe[src*="mayzaent"], iframe[src*="greentrafsa"], iframe[src*="rallytrck"], iframe[src*="tsyndicate"], iframe[src*="exoclick"], iframe[src*="magsrv"], iframe[src*="juicyads"], iframe[src*="trafficjunky"], a[href*="mayzaent"], a[href*="greentrafsa"], a[href*="rallytrck"], a[href*="tsyndicate"], a[href*="exoclick"], a[href*="magsrv"], ins[class*="eas"]';
  var rawOpen = window.open;
  window.open = function(){ try { return null; } catch (e) { return rawOpen ? rawOpen.apply(window, arguments) : null; } };

  function isProtectedContainer(el) {
    if (!el || el.nodeType !== 1) return true;
    var tag = (el.tagName || '').toUpperCase();
    if (tag === 'HTML' || tag === 'BODY' || tag === 'MAIN' || tag === 'HEADER' || tag === 'NAV' || tag === 'FOOTER' || tag === 'ARTICLE') {
      return true;
    }
    var cls = typeof el.className === 'string' ? el.className : '';
    if (/\\b(min-h-screen|max-w-7xl|container)\\b/.test(cls)) return true;
    try {
      if (el.querySelector('main, nav, header, footer, video, form, .plyr, [id*="player"]')) return true;
    } catch (e) {}
    return false;
  }

  function isAdLayer(el) {
    if (isProtectedContainer(el)) return false;
    var cls = typeof el.className === 'string' ? el.className : '';
    if (/adsbox|adbox|popup-ad|ad-popup|ad-modal|ad-overlay/i.test(cls)) return true;

    var cs = null;
    try { cs = window.getComputedStyle(el); } catch (e) {}
    var isFixed = (cs && cs.position === 'fixed') || /\\bfixed\\b/.test(cls);

    // 1) 包含广告标记的紧凑容器（非页面主干，子元素较少）
    try {
      if (el.querySelector && el.querySelector(AD_SEL)) {
        if (isFixed) return true;
        if (el.children.length <= 6 && (el.offsetHeight || 0) <= 420 && ((el.textContent || '').trim().length <= 120)) {
          return true;
        }
      }
    } catch (e) {}

    // 2) 首页右下角/底部残留的空壳漂浮广告窗（fixed 定位 + 关闭按钮 X / SVG 按钮）
    if (isFixed) {
      var rectH = el.offsetHeight || 0;
      var txt = (el.textContent || '').trim();
      if (rectH <= 420 && txt.length <= 40 && el.children.length <= 6) {
        if (/^(close|关闭|[×xX✕✖])$/i.test(txt)) return true;
        try {
          var hasBtn = el.querySelector('button, [role="button"], [class*="close" i], svg');
          var hasAdRemnant = el.querySelector('iframe, ins, [data-ad-marker], a[target="_blank"], img') || el.children.length <= 3;
          if (hasBtn && hasAdRemnant) return true;
        } catch (e) {}
      }
    }
    return false;
  }

  function sweep(root) {
    var scope = root && root.querySelectorAll ? root : document;
    // 先清理所有带 data-ad-marker 的外层小容器或 fixed 容器
    try {
      var markers = scope.querySelectorAll('[data-ad-marker]');
      for (var m = 0; m < markers.length; m++) {
        var cur = markers[m].parentElement;
        var target = markers[m];
        for (var depth = 0; cur && depth < 5; depth++, cur = cur.parentElement) {
          if (isProtectedContainer(cur)) break;
          if (isAdLayer(cur)) { target = cur; }
        }
        try { target.remove(); } catch (e) {}
      }
    } catch (e) {}

    var nodes = scope.querySelectorAll('div, section, aside, ins');
    for (var i = 0; i < nodes.length; i++) {
      if (isAdLayer(nodes[i])) {
        try { nodes[i].remove(); } catch (e) {}
      }
    }
  }

  function start() {
    sweep(document);
    if (typeof MutationObserver === 'function') {
      var mo = new MutationObserver(function(muts) {
        for (var m = 0; m < muts.length; m++) {
          var added = muts[m].addedNodes || [];
          for (var n = 0; n < added.length; n++) {
            var el = added[n];
            if (el && el.nodeType === 1) {
              if (isAdLayer(el)) { try { el.remove(); } catch (e) {} }
              else if (el.querySelectorAll) sweep(el);
            }
          }
        }
      });
      try { mo.observe(document.documentElement, { childList: true, subtree: true }); } catch (e) {}
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();</script>`;

let body = $response.body || "";

// 1. 将广告 script / iframe 标签替换为隐藏的 data-ad-marker 标记节点（保留父容器特征以便 CSS :has 与 JS 连壳拔除）
const hostAlt = AD_HOSTS.join("|");
body = body.replace(
  new RegExp('<script[^>]*src=["\'][^"\']*(?:' + hostAlt + ')[^"\']*["\'][^>]*>\\s*</script>', "gi"),
  '<i data-ad-marker="1" style="display:none !important"></i>'
);
body = body.replace(
  new RegExp('<iframe[^>]*src=["\'][^"\']*(?:' + hostAlt + ')[^"\']*["\'][^>]*>\\s*</iframe>', "gi"),
  '<i data-ad-marker="1" style="display:none !important"></i>'
);

// 2. 注入 CSS 与运行时清理
const inject = "<style>" + CSS + "</style>" + BLOCK_POPUP;
if (body.indexOf("</head>") !== -1) {
  body = body.replace("</head>", inject + "</head>");
} else if (body.indexOf("<body") !== -1) {
  body = body.replace("<body", inject + "<body");
} else {
  body = inject + body;
}

$done({ body: body });
