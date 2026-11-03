/***********************************************
> 应用名称：高德地图内容净化（本地维护 v2）
> 作用：屏蔽「我的」页与首页的社区 / 推荐卡片
>       猜你喜欢、达人任务、好友动态、热门活动
> 更新时间：2026-11-03
> 设计原则：黑名单删除 + 全程异常兜底 + 容器类型自适应

v2 修的两个致命问题（v1 完全失效的原因）：
  1. cardList 是「对象」不是数组。上游脚本用的是
     Object.values(obj.data.cardList).filter(...)，
     v1 只判断 Array.isArray 并调 splice，所以一次都没进去过。
  2. 图片海报位（首页海报墙）响应里没有文字，按标题关键字永远匹配不到。
     那类走 AmapSafe.conf 的 reject 拦请求，不靠本脚本。
***********************************************/

var KEYWORDS = [
  '猜你喜欢', '达人任务', '好友动态',
  '热门活动', '扫街榜', '周边精选',
  '为你推荐', '大家都在看'
];
// 太长的字符串通常是正文/描述，不做匹配，避免误删正常内容
var MAX_TEXT_LEN = 60;

function amapHitText(v) {
  if (typeof v !== 'string' || v.length === 0 || v.length > MAX_TEXT_LEN) return false;
  for (var i = 0; i < KEYWORDS.length; i++) {
    if (v.indexOf(KEYWORDS[i]) !== -1) return true;
  }
  return false;
}

// 只看对象「第一层」的字符串值。不递归父子关系：避免命中一个容器对象后
// 把它连同里面的正常卡片一起删掉。
function amapHit(obj) {
  if (!obj || typeof obj !== 'object') return false;
  for (var k in obj) {
    if (amapHitText(obj[k])) return true;
  }
  return false;
}

var amapRemoved = 0;

// 数组用 splice 反向删；普通对象用 delete 删键。
// v1 只处理了数组，而高德的 cardList 是 {key: card} 形式的对象。
function amapClean(node) {
  if (node === null || typeof node !== 'object') return;

  if (Object.prototype.toString.call(node) === '[object Array]') {
    for (var i = node.length - 1; i >= 0; i--) {
      if (amapHit(node[i])) {
        node.splice(i, 1);
        amapRemoved++;
      } else {
        amapClean(node[i]);
      }
    }
    return;
  }

  // 先收集再删：不要在遍历过程中改正在遍历的对象
  var del = [];
  for (var k in node) {
    if (amapHit(node[k])) del.push(k);
  }
  for (var j = 0; j < del.length; j++) {
    delete node[del[j]];
    amapRemoved++;
  }
  // 剩下的继续下钻（卡片内部可能还有嵌套列表）
  for (var k2 in node) {
    amapClean(node[k2]);
  }
}

// ===== 入口必须放末尾：var 声明不提升，放顶部调用会拿到 undefined =====
var amapBody = ($response && $response.body) ? $response.body : '';
var amapObj = null;
try {
  amapObj = JSON.parse(amapBody);
} catch (e) {
  amapObj = null;
}

// 非 JSON（protobuf / 空响应 / 网关错误页）→ 原样放行。
// 这一步是整个脚本的安全底线：上游就是在这里没有兜底，抛异常后拿不到 $done，
// QX 的请求一直挂到超时，表现为「网络不畅」。
if (amapObj === null || typeof amapObj !== 'object') {
  $done({});
} else {
  try {
    amapClean(amapObj);
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
