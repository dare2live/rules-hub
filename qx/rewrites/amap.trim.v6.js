/***********************************************
> 应用名称：高德地图内容净化（本地维护 v5）
> 更新时间：2026-11-03
> 设计原则：按「卡片容器」定位卡片 + 按 dataType / 标题 / 关键字三重判定 + 全程异常兜底

v5 相对 v4 的改动（首页榜单卡一张都没删掉）：

  v4 只认「带 dataType 的对象」，且 dataType 黑名单里只有
  feed/friend/social/dynamic/task/activity/banner/recommend 这些词。
  首页的扫街榜卡片（足球場榜、賞紅葉榜、專程咖啡榜、早晨 brunch 榜）
  dataType 不在黑名单里，标题里也没有「扫街榜」三个字（那是卡片上的
  标签胶囊，标题是「XX榜」），所以 v4 一次都没命中 —— 静默失效。

  v5 换定位方式：不再靠全树猜「哪个对象像卡片」，而是先找**已知的卡片容器**
  （cardList / cards / modules / feeds / sections），容器里的元素就是卡片。
  这是从上游解码出来的真实结构：main-page 的卡片在 data.cardList（对象），
  nearbyrec_smart 的在 data.modules（数组）。

  判定规则（任一命中即删，白名单优先）：
    a. dataType 命中黑名单（新增 rank/ranking/board/chart/hotlist/toplist/poilist）
    b. 标题字段（title/name/mainTitle/subTitle/cardTitle）含「榜」或「排行」
       —— 简繁同形，不依赖 dataType 也不依赖「扫街榜」这个标签词
    c. 卡片子树里有 ≤30 字的可见文字命中关键字（简繁两套）

  白名单（DT_SAFE）优先于黑名单：weather/forecast/search/navi/route/login
  /myorder/frequentlocation/feedback 这些功能卡永远不删 —— 首页的天气卡
  和搜索入口必须留着，否则页面变成一片空白。

  安全阀按**容器**粒度生效：某个容器里算出「所有元素都该删」时，
  这个容器一张都不删、原样放行。宁可没效果，也不能整块清空。

  兜底：如果一个已知容器都没找到（或找到但没删任何东西），再退回 v4 的
  「全树按 dataType 收集卡片」逻辑，兼容结构不在已知容器名里的页面。

关于调试：QX 的 $notify 在设备上必须开了通知权限才有提示（关掉是静默 no-op）。
  所以不用通知做探针，改成在「第一张保留的卡片标题」后面追加
  〔删除数/卡片总数〕。**只在「一张都没删掉」时才追加** —— 成功时界面干净，
  失败时又能区分两种情况：
    完全没有方括号 → 脚本没跑到这个接口（URL 规则没匹配上）
    〔0/N〕        → 脚本跑到了，找到了 N 张卡但认不出一张该删
    〔0/0〕        → 跑到了，但连卡片容器都没找到
  把 DELETE_MARK 关掉就彻底不显示任何标记。

安全底线：任何异常都必须走到 $done，绝不挂死请求。
***********************************************/

// 失败时才在卡片标题上追加诊断标记（成功时不显示，避免影响观感）
var DELETE_MARK = true;

// 可见文字关键字（简体 + 繁体）。服务端按 locale 下发。
var KEYWORDS = [
  '猜你喜欢', '猜你喜歡',
  '达人任务', '達人任務',
  '好友动态', '好友動態',
  '热门活动', '熱門活動',
  '扫街榜', '掃街榜',
  '周边精选', '週邊精選',
  '为你推荐', '為你推薦',
  '大家都在看', '大家都在搜'
];

// 标题类字段：这些字段里出现「榜」就判定为榜单卡。
// 「榜」简繁同形，比「扫街榜」标签词可靠 —— 标签往往是图片。
var TITLE_FIELDS = ['title', 'name', 'mainTitle', 'subTitle', 'titleText', 'cardTitle'];
var RANK_RE = /(榜|排行)/;

// dataType 黑名单：卡片身份是英文 camelCase，比标题稳定。
var DT_BLACK = /(feed|friend|social|dynamic|daren|task|activity|banner|advert|promo|recommend|discover|community|ugc|rank|ranking|board|chart|hotlist|toplist|poilist)/i;
// 白名单优先：这些即使命中上面的词也绝不删（feedback 里含 feed，
// weather 是首页天气卡，search/navi 是功能入口）。
var DT_SAFE = /(feedback|myorder|frequentlocation|weather|forecast|temperature|search|navi|route|login)/i;

// 已知的卡片容器名。容器里的元素就是卡片，逐个判断。
var CARD_KEYS = ['cardList', 'cards', 'modules', 'feeds', 'sections'];

var TEXT_MAX = 30;      // 只认短文本，长的是正文/描述
var TEXT_DEPTH = 3;     // 卡片内部找文字最多钻 3 层
var WALK_MAX = 12;      // 整棵树最多钻 12 层

function amapIsObj(o) {
  return o !== null && typeof o === 'object';
}
function amapIsArr(o) {
  return Object.prototype.toString.call(o) === '[object Array]';
}

function amapTextHit(v) {
  if (typeof v !== 'string' || v.length === 0 || v.length > TEXT_MAX) return false;
  for (var i = 0; i < KEYWORDS.length; i++) {
    if (v.indexOf(KEYWORDS[i]) !== -1) return true;
  }
  return false;
}

function amapHasText(node, depth) {
  if (!amapIsObj(node) || depth > TEXT_DEPTH) return false;
  var i, v;
  if (amapIsArr(node)) {
    for (i = 0; i < node.length; i++) {
      v = node[i];
      if (amapTextHit(v)) return true;
      if (amapHasText(v, depth + 1)) return true;
    }
    return false;
  }
  for (var k in node) {
    v = node[k];
    if (amapTextHit(v)) return true;
    if (amapHasText(v, depth + 1)) return true;
  }
  return false;
}

// 标题里出现「榜」/「排行」→ 榜单卡。只看明确的标题字段，不扫全文，
// 避免描述文字里的「榜」误伤。
// depth 允许钻 2 层：卡片常被包一层 {data:{title:...}} 或 {base:{title:...}}。
function amapTitleRank(o, depth) {
  if (!amapIsObj(o) || depth > 2) return false;
  var i, k;
  if (amapIsArr(o)) {
    for (i = 0; i < o.length; i++) {
      if (amapTitleRank(o[i], depth + 1)) return true;
    }
    return false;
  }
  for (i = 0; i < TITLE_FIELDS.length; i++) {
    var v = o[TITLE_FIELDS[i]];
    if (typeof v === 'string' && v.length > 0 && v.length <= 20 && RANK_RE.test(v)) return true;
  }
  for (k in o) {
    if (amapIsObj(o[k]) && amapTitleRank(o[k], depth + 1)) return true;
  }
  return false;
}

// 卡片身份：带字符串 dataType 的对象
function amapDataType(o) {
  if (!amapIsObj(o) || amapIsArr(o)) return '';
  return typeof o.dataType === 'string' ? o.dataType : '';
}

function amapCardBad(card) {
  var dt = amapDataType(card);
  if (dt && DT_SAFE.test(dt)) return false;          // 白名单优先，永不删
  if (dt && DT_BLACK.test(dt)) return true;
  if (amapTitleRank(card)) return true;              // 标题含「榜」
  return amapHasText(card, 0);                       // 关键字兜底
}

// 处理一个卡片容器：逐元素判定，全命中则整个容器不删（安全阀）
function amapTrimOne(container) {
  var i, k, c;
  var all = [], bad = [];

  if (amapIsArr(container)) {
    for (i = 0; i < container.length; i++) {
      c = container[i];
      if (!amapIsObj(c)) continue;
      all.push(i);
      if (amapCardBad(c)) bad.push(i);
    }
    // 安全阀：一张都不留时不做任何删除
    if (all.length === 0 || bad.length === 0 || bad.length >= all.length) {
      return { removed: 0, total: all.length };
    }
    bad.sort(function (a, b) { return b - a; });
    for (i = 0; i < bad.length; i++) container.splice(bad[i], 1);
    return { removed: bad.length, total: all.length };
  }

  for (k in container) {
    c = container[k];
    if (!amapIsObj(c)) continue;
    all.push(k);
    if (amapCardBad(c)) bad.push(k);
  }
  if (all.length === 0 || bad.length === 0 || bad.length >= all.length) {
    return { removed: 0, total: all.length };
  }
  for (i = 0; i < bad.length; i++) delete container[bad[i]];
  return { removed: bad.length, total: all.length };
}

// 全树找已知容器名，逐个处理
function amapTrimContainers(root) {
  var removed = 0, total = 0, found = 0;

  function walk(node, depth) {
    if (!amapIsObj(node) || depth > WALK_MAX) return;
    var k, v;
    if (amapIsArr(node)) {
      for (var i = 0; i < node.length; i++) walk(node[i], depth + 1);
      return;
    }
    for (k in node) {
      v = node[k];
      if (CARD_KEYS.indexOf(k) !== -1 && amapIsObj(v) && !amapDataType(v)) {
        // 名字对上，且它本身不是一张卡片（有些卡片的 dataType 就叫 CardList）
        var r = amapTrimOne(v);
        removed += r.removed;
        total += r.total;
        found++;
        continue;
      }
      walk(v, depth + 1);
    }
  }
  walk(root, 0);
  return { removed: removed, total: total, found: found };
}

// ---- 兜底：v4 的全树 dataType 收集（结构不在已知容器名里时用）----
function amapCollectCards(root) {
  var out = [];
  function walk(node, depth) {
    if (!amapIsObj(node) || depth > WALK_MAX) return;
    var i, k, c;
    if (amapIsArr(node)) {
      for (i = 0; i < node.length; i++) {
        c = node[i];
        if (amapDataType(c)) out.push({ p: node, k: i, c: c });
        else walk(c, depth + 1);
      }
      return;
    }
    for (k in node) {
      c = node[k];
      if (amapDataType(c)) out.push({ p: node, k: k, c: c });
      else walk(c, depth + 1);
    }
  }
  walk(root, 0);
  return out;
}

function amapRemoveCards(recs) {
  var i, r;
  var arrRecs = [];
  for (i = 0; i < recs.length; i++) {
    r = recs[i];
    if (amapIsArr(r.p)) arrRecs.push(r);
    else delete r.p[r.k];
  }
  arrRecs.sort(function (a, b) { return b.k - a.k; });
  for (i = 0; i < arrRecs.length; i++) arrRecs[i].p.splice(arrRecs[i].k, 1);
}

// ai_rec：清空「元素为对象的数组」，保留基本类型数组（配置 / 枚举 / 坐标）
function amapStrip(node, depth) {
  if (!amapIsObj(node) || depth > WALK_MAX) return 0;
  var n = 0;
  if (amapIsArr(node)) {
    if (node.length > 0 && amapIsObj(node[0])) {
      node.length = 0;
      return 1;
    }
    return 0;
  }
  for (var k in node) n += amapStrip(node[k], depth + 1);
  return n;
}

// 调试标记：写进第一张保留卡片的可见标题，绕开通知权限
function amapMark(root, removed, total) {
  var tag = ' 〔' + removed + '/' + total + '〕';
  var cards = amapCollectCards(root);
  for (var i = 0; i < cards.length; i++) {
    var c = cards[i].c;
    var f = (typeof c.title === 'string') ? 'title'
          : (typeof c.name === 'string' ? 'name' : null);
    if (f) {
      c[f] = c[f] + tag;
      return true;
    }
  }
  var marked = false;
  function walk(n, d) {
    if (marked || !amapIsObj(n) || d > 6) return;
    if (amapIsArr(n)) {
      for (var j = 0; j < n.length; j++) walk(n[j], d + 1);
      return;
    }
    if (typeof n.title === 'string' && n.title.length <= TEXT_MAX) {
      n.title = n.title + tag;
      marked = true;
      return;
    }
    for (var k in n) walk(n[k], d + 1);
  }
  walk(root, 0);
  return marked;
}

// ===== 入口放末尾：var 声明不提升 =====
var amapUrl = ($request && $request.url) ? $request.url : '';
var amapBody = ($response && $response.body) ? $response.body : '';
var amapObj = null;
try {
  amapObj = JSON.parse(amapBody);
} catch (e) {
  amapObj = null;
}

if (!amapIsObj(amapObj)) {
  // 非 JSON（protobuf / 空响应 / 网关错误页）→ 原样放行
  $done({});
} else {
  var amapRemoved = 0;
  var amapTotal = 0;
  var amapSerialized = false;

  try {
    if (amapUrl.indexOf('/ai_rec/') !== -1) {
      // 首页底部信息流：清空列表而不是拒绝请求（拒绝会让 App 渲染「网络不畅」）
      amapRemoved = amapStrip(amapObj, 0);
      amapSerialized = true;
    } else {
      // 1) 先按已知容器名处理（main-page 的 cardList、nearbyrec 的 modules）
      var amapRes = amapTrimContainers(amapObj);
      amapRemoved = amapRes.removed;
      amapTotal = amapRes.total;

      // 2) 容器没找到或没删到东西 → 退回全树 dataType 收集
      if (amapRemoved === 0) {
        var amapCards = amapCollectCards(amapObj);
        if (amapCards.length > 0) {
          amapTotal = amapCards.length;
          var amapBad = [];
          for (var amapI = 0; amapI < amapCards.length; amapI++) {
            if (amapCardBad(amapCards[amapI].c)) amapBad.push(amapCards[amapI]);
          }
          if (amapBad.length > 0 && amapBad.length < amapCards.length) {
            amapRemoveCards(amapBad);
            amapRemoved = amapBad.length;
          }
        }
      }

      // 探针只在失败时出现：成功时界面干净，失败时能区分
      // 「没跑到」（无标记）和「跑到了但认不出」（〔0/N〕）
      if (DELETE_MARK && amapRemoved === 0) {
        amapSerialized = amapMark(amapObj, amapRemoved, amapTotal);
      }
    }
  } catch (e) {
    amapObj = null;
  }

  if (amapObj === null) {
    $done({});                                  // 处理出错 → 原样放行
  } else if (amapRemoved === 0 && !amapSerialized) {
    $done({});                                  // 没改动 → 不重新序列化
  } else {
    $done({ body: JSON.stringify(amapObj) });
  }
}
