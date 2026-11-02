/***********************************************
> 应用名称：高德地图内容净化（本地维护）
> 作用：屏蔽首页与「我的」页的信息流 / 社区卡片
>       猜你喜欢、达人任务、好友动态
> 更新时间：2026-11-02
> 设计原则：黑名单删除 + 全程异常兜底
***********************************************/

// 上游 830f361b-amap.js 的「我的页面」用的是白名单保留（只留 MyOrderCard /
// FrequentLocation 两种 dataType），高德一改字段名就把整页清空 —— 这正是之前
// 「我的页面加载不出」的原因之一。
// 这里反过来做：只按标题文本做黑名单删除。匹配不上就保持原样，最坏是没效果，
// 绝不会把整页清成空白，也不会因为字段缺失而挂住请求。

var KEYWORDS = ['猜你喜欢', '达人任务', '好友动态'];
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
  for (var k in node) {
    amapClean(node[k]);
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
