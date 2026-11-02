/***********************************

MissAV 去广告（Rules Hub 本地维护版）

上游 ddgksf2013 的版本停在 2025.12，站点的广告位已经换了一轮。
本文件由 Rules Hub 自己维护。

改名说明（重要）：
  QX 按 URL 缓存远程脚本本体，只改内容、不改文件名时设备不会重新下载，
  线上改了等于没改，而且不报错。所以每次改脚本都要换文件名 ——
  文件名本身就是缓存键。旧的 missav.ads.js 已在 gh-pages 上 404。

本次修的问题：
  广告内容被摘掉了，但装它的那层容器还在 —— 一个透明的 fixed 浮层，
  外加一个关闭按钮 X。容器是全屏透明的，会吃掉点击，X 也一直挂在角落。
  光隐藏内容不够，必须把容器本身干掉。

[rewrite_local]

^https?:\/\/missav\.(ws|live|com|ai)\/(?!(.*(api|login|cdn-cgi|verify|auth|captch|(\.(js|css|jpg|jpeg|png|webp|gif|zip|woff|woff2|m3u8|mp4|mov|m4v|avi|mkv|flv|rmvb|wmv|rm|asf|asx|mp3|json|ico|otf|ttf))))) url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/missav.clean.js

***********************************/

const AD_HOSTS = ["mayzaent", "greentrafsa", "rallytrck"];

// 已知广告位。类名用子串匹配，站点改版换 Tailwind 类名也能命中。
const CSS = `
a[href^='https://theporndude.com'],
a[href*='mycomic'],
a[href*='myavlive'],
a[href*='bit.ly'],
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
div.playerThumbWrapper--bcYD7:has(a[href*='greentrafsa']),

/* 透明浮层：fixed 定位的容器，里面装着广告链接或关闭按钮，整块干掉。
   用 :has() 限定，避免误伤播放器控制条（它也是 fixed bottom）。 */
div[class*='fixed']:has(a[href*='mayzaent']),
div[class*='fixed']:has(a[href*='greentrafsa']),
div[class*='fixed']:has(a[href*='rallytrck']),
div[class*='fixed']:has(a[href*='bit.ly']),
div[class*='fixed']:has(iframe),
div[class*='fixed']:has([class*='close' i]),
/* 广告遮罩与弹窗（按类名子串，不依赖具体 Tailwind 类名） */
[class*='adsbox' i],
[class*='adbox' i],
[class*='popup-ad' i],
[class*='ad-popup' i],
[class*='ad-modal' i],
[class*='ad-overlay' i] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
}
body { overflow-x: hidden !important; }
`;

// 运行时清理：浮层经常是 JS 延迟插入的，CSS 选择器管不到后加的节点。
// 用 MutationObserver 盯着 DOM，命中就删。
const BLOCK_POPUP = `<script>(function(){
  var AD_RE = /mayzaent|greentrafsa|rallytrck|theporndude|bit\\.ly/i;
  var raw = window.open;
  window.open = function(){ try { return null; } catch (e) { return raw.apply(window, arguments); } };

  function isAdLayer(el) {
    if (!el || el.nodeType !== 1) return false;
    var cls = el.className || '';
    if (typeof cls !== 'string') cls = '';
    var cs = getComputedStyle(el);
    var fixed = cs && cs.position === 'fixed';
    var html = el.innerHTML || '';
    // 1) 里面是广告链接 / iframe
    if (AD_RE.test(html)) return true;
    // 2) 浮层上只有一个关闭按钮（就是那种透明浮层 + 一个 X）
    if (fixed) {
      var txt = (el.textContent || '').trim();
      if (el.children.length <= 3 && /close|关闭|^\\s*[×xX]\\s*$/i.test(txt)) return true;
      if (/close/i.test(cls) && el.children.length <= 3) return true;
    }
    // 3) 类名里写着广告
    return /adsbox|adbox|popup-ad|ad-popup|ad-modal|ad-overlay/i.test(cls);
  }

  function sweep(root) {
    var nodes = (root || document).querySelectorAll('div, section, aside');
    for (var i = 0; i < nodes.length; i++) {
      if (isAdLayer(nodes[i])) { try { nodes[i].remove(); } catch (e) {} }
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
              else if (el.querySelector) sweep(el);
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

// 1. 直接摘掉广告的 script / iframe 标签，比事后隐藏更干净
const hostAlt = AD_HOSTS.join("|");
body = body.replace(
  new RegExp('<script[^>]*src="[^"]*(?:' + hostAlt + ')[^"]*"[^>]*>\\s*</script>', "gi"), ""
);
body = body.replace(
  new RegExp('<iframe[^>]*src="[^"]*(?:' + hostAlt + ')[^"]*"[^>]*>\\s*</iframe>', "gi"), ""
);

// 2. 注入 CSS 与运行时清理
const inject = "<style>" + CSS + "</style>" + BLOCK_POPUP;
if (body.indexOf("</head>") !== -1) {
  body = body.replace("</head>", inject + "</head>");
} else {
  body = inject + body;
}

$done({ body: body });
