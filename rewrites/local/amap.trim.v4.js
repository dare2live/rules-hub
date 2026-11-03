/***********************************************
> 应用名称：高德地图内容净化（本地维护 v4）
> 更新时间：2026-11-03
> 设计原则：按卡片身份（dataType）整卡删除 + 全程异常兜底

v4 相对 v3 的改动：

  v3 按「标题文字」在原 JSON 里递归删除命中的对象。问题有两个：
    1. 删掉的往往只是卡片内部的内容节点，卡片容器本身还在 ——
       于是内容没了、占位的 banner 还留着（用户实测）。
    2. 深层匹配一旦命中，会把承载它的祖先对象一起删掉，
       极端情况下能删到 data 这一层，整页空白。

  v4 换个判断依据：高德的卡片都有 dataType（上游脚本就是靠
  x.dataType == 'MyOrderCard' 过滤的），所以先按 dataType 认出「卡片」，
  再决定整张卡片删不删。删除作用于卡片本身，容器和它的 banner 一起走。

  判定规则（任一命中即删）：
    a. dataType 命中黑名单正则（feed/friend/social/dynamic/task/activity/
       banner/advert/promo/recommend/discover/community/ugc）
    b. 卡片子树里有 ≤30 字的可见文字命中关键字（简繁两套）

  安全阀：如果算出「所有卡片都该删」，就一张都不删、原样放行 ——
  宁可没效果，也不能把整页清空（这是上游白名单方案踩过的坑）。

关于调试：QX 的 $notify 在重写脚本里可用，但设备上必须开了通知权限，
  iOS 设置里关掉就完全没有提示（不报错）。所以 v4 不用通知做探针，
  改成在「第一张保留的卡片标题」后面追加命中计数 〔删除数/卡片总数〕。
  看到 〔0/6〕 说明脚本跑到了但一张都没认出来；看到 〔2/6〕 说明生效。
  DEBUG 关掉后不再追加任何标记。

安全底线：任何异常都必须走到 $done，绝不挂死请求。
***********************************************/

var DEBUG = true;

// 简体 + 繁体。服务端按 locale 下发，繁体环境会给繁体标题。
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

// dataType 黑名单：卡片身份是英文 camelCase，比标题稳定得多。
var DT_BLACK = /(feed|friend|social|dynamic|daren|task|activity|banner|advert|promo|recommend|discover|community|ugc)/i;
// 白名单优先：这些即使命中上面的词也绝不删（feedback 里含 feed）。
var DT_SAFE = /(feedback|myorder|frequentlocation)/i;

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

// 卡片身份：带字符串 dataType 的对象
function amapDataType(o) {
  if (!amapIsObj(o) || amapIsArr(o)) return '';
  return typeof o.dataType === 'string' ? o.dataType : '';
}

function amapCardBad(card) {
  var dt = amapDataType(card);
  if (dt && !DT_SAFE.test(dt) && DT_BLACK.test(dt)) return true;
  return amapHasText(card, 0);
}

// 收集所有卡片：{p: 父容器, k: 键或下标, c: 卡片}
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

// 删除：数组按下标倒序 splice，对象直接 delete
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
  // 兜底：一张 dataType 卡片都没找到时，标在任意短标题上，
  // 这样「页面没变化」也能区分是「脚本没跑到」还是「识别不出卡片」。
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
      amapRemoved = amapStrip(amapObj, 0);
      amapSerialized = true;
    } else {
      var amapCards = amapCollectCards(amapObj);
      amapTotal = amapCards.length;
      var amapBad = [];
      for (var amapI = 0; amapI < amapCards.length; amapI++) {
        if (amapCardBad(amapCards[amapI].c)) amapBad.push(amapCards[amapI]);
      }
      // 安全阀：全部命中时不删（防整页清空）
      if (amapTotal > 0 && amapBad.length < amapTotal) {
        amapRemoveCards(amapBad);
        amapRemoved = amapBad.length;
      }
      if (DEBUG) amapSerialized = amapMark(amapObj, amapRemoved, amapTotal);
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
