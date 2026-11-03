/***********************************************
> 应用名称：高德地图内容净化（本地维护 v3）
> 作用：屏蔽「我的」页与首页的社区 / 推荐卡片
> 更新时间：2026-11-03
> 设计原则：黑名单删除 + 全程异常兜底 + 容器类型自适应

v3 修的两个问题：

  1. 首页出现「网络不畅，请稍后重试」。
     v2 把 ai_rec 交给 AmapSafe.conf 用 reject-dict 拒绝请求 ——
     App 收到空字典会判定「请求失败」，于是渲染成错误占位：
     卡片确实是没了，但换来一行错误文案。
     v3 改成 STRIP 模式：解析成功就把「内容列表」清空后正常返回，
     App 认为请求成功、只是没有内容，不会报错。

  2. 「我的」页一点变化都没有。
     手机是繁体环境，界面上是 達人任務 / 好友動態 / 猜你喜歡，
     而 v2 的关键字表只有简体写法，所以一条都匹配不上。
     v3 同时收简繁两套写法；另外补了二层深匹配兜底
     （浅层一个都没命中时才启用，避免误删大容器）。

诊断：DEBUG=true 时用 $notify 报告命中接口的真实情况
     （URL / 是否 JSON / 顶层键 / 卡片标题样本）。
     拿到报告确认结构后再关掉。

安全底线：任何异常都必须走到 $done，绝不挂死请求。
***********************************************/

var DEBUG = true;

// 简体 + 繁体两套写法。手机是繁体环境时，服务端很可能按 locale 下发繁体标题。
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

var MAX_TEXT_LEN = 60;   // 浅层：太长的字符串是正文/描述，不匹配
var DEEP_TEXT_LEN = 30;  // 深层：只认短标题，避免误删大容器
var DEEP_MAX = 3;

function amapHitText(v, maxLen) {
  if (typeof v !== 'string' || v.length === 0 || v.length > maxLen) return false;
  for (var i = 0; i < KEYWORDS.length; i++) {
    if (v.indexOf(KEYWORDS[i]) !== -1) return true;
  }
  return false;
}

// 浅层：只看对象第一层的字符串值。
function amapHitShallow(obj) {
  if (!obj || typeof obj !== 'object') return false;
  for (var k in obj) {
    if (amapHitText(obj[k], MAX_TEXT_LEN)) return true;
  }
  return false;
}

// 深层：往下钻几层找短标题（卡片标题常嵌在 data.xxx 里）。
function amapHitDeep(obj, depth) {
  if (!obj || typeof obj !== 'object' || depth > DEEP_MAX) return false;
  for (var k in obj) {
    var v = obj[k];
    if (amapHitText(v, DEEP_TEXT_LEN)) return true;
    if (v && typeof v === 'object' && amapHitDeep(v, depth + 1)) return true;
  }
  return false;
}

function amapHit(obj, deep) {
  return deep ? amapHitDeep(obj, 0) : amapHitShallow(obj);
}

var amapRemoved = 0;

function amapClean(node, deep) {
  if (node === null || typeof node !== 'object') return;

  if (Object.prototype.toString.call(node) === '[object Array]') {
    for (var i = node.length - 1; i >= 0; i--) {
      if (amapHit(node[i], deep)) {
        node.splice(i, 1);
        amapRemoved++;
      } else {
        amapClean(node[i], deep);
      }
    }
    return;
  }

  // 先收集再删：不要在遍历过程中改正在遍历的对象
  var del = [];
  for (var k in node) {
    if (amapHit(node[k], deep)) del.push(k);
  }
  for (var j = 0; j < del.length; j++) {
    delete node[del[j]];
    amapRemoved++;
  }
  for (var k2 in node) amapClean(node[k2], deep);
}

// STRIP 模式：清空「元素为对象的数组」= 内容列表。
// 保留基本类型数组（通常是配置 / 枚举 / 坐标，动了会破坏响应结构）。
function amapStrip(node, depth) {
  if (node === null || typeof node !== 'object' || depth > 12) return;
  if (Object.prototype.toString.call(node) === '[object Array]') {
    if (node.length > 0 && typeof node[0] === 'object') {
      node.length = 0;
      amapRemoved++;
    }
    return;
  }
  for (var k in node) amapStrip(node[k], depth + 1);
}

// 诊断用：取几个卡片标题样本，用来确认响应里到底有没有目标文字
function amapProbe(obj) {
  var out = [];
  function walk(n, d) {
    if (d > 5 || out.length >= 3) return;
    if (!n || typeof n !== 'object') return;
    if (Object.prototype.toString.call(n) === '[object Array]') {
      if (n.length > 0 && typeof n[0] === 'object') {
        var s = [];
        for (var k in n[0]) {
          if (typeof n[0][k] === 'string' && n[0][k].length <= 30) s.push(n[0][k].slice(0, 14));
        }
        if (s.length) out.push('[' + n.length + ']' + s.slice(0, 2).join('|'));
      }
      return;
    }
    for (var k in n) walk(n[k], d + 1);
  }
  walk(obj, 0);
  return out.join(' ');
}

// ===== 入口必须放末尾：var 声明不提升，放顶部调用会拿到 undefined =====
var amapUrl = ($request && $request.url) ? $request.url : '';
var amapBody = ($response && $response.body) ? $response.body : '';
var amapObj = null;
try {
  amapObj = JSON.parse(amapBody);
} catch (e) {
  amapObj = null;
}

var amapIsJson = (amapObj !== null && typeof amapObj === 'object');
var amapIsRec = amapUrl.indexOf('/ai_rec/') !== -1;

if (DEBUG && typeof $notify === 'function') {
  var amapPath = amapUrl.replace(/^https?:\/\//, '').split('?')[0];
  var amapKeys = amapIsJson ? Object.keys(amapObj).join(',') : '-';
  $notify(
    '高德净化 DEBUG',
    amapPath.slice(-38),
    'json=' + amapIsJson + ' len=' + amapBody.length +
    ' keys=' + amapKeys.slice(0, 50) +
    (amapIsJson ? ' | ' + amapProbe(amapObj).slice(0, 60) : '')
  );
}

// 非 JSON（protobuf / 空响应 / 网关错误页）→ 原样放行。
// 这是整个脚本的安全底线：上游就是在这里没兜底，抛异常后拿不到 $done，
// QX 的请求一直挂到超时，表现为「某个页面转圈 / 网络不畅」。
if (!amapIsJson) {
  $done({});
} else {
  try {
    if (amapIsRec) {
      amapStrip(amapObj, 0);
    } else {
      amapClean(amapObj, false);
      // 浅层一个都没命中才升级到深层匹配，保守优先
      if (amapRemoved === 0) amapClean(amapObj, true);
    }
  } catch (e) {
    amapObj = null;
  }
  if (amapObj === null) {
    $done({});
  } else if (amapRemoved === 0) {
    // 没命中任何东西，原样放行，不重新序列化
    $done({});
  } else {
    $done({ body: JSON.stringify(amapObj) });
  }
}
