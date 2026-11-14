/*************************************

项目名称：FotMob+ 会员解锁（本地维护版）
上游参考：kienphan2702/Shadowrocket — Javascript/revenuecat.js（含 FotMob 条目）
          hoo-dles/morphe-patches — fotmob/plus/EnablePlusPatch
          heval99/Heval-Morphe-Patches — fotmob/misc/promotions

原理：
  FotMob 的会员态由 RevenueCat 下发（抓包可见 api.revenuecat.com:443，
  6KB 下行 / 2KB 上行）。RevenueCat 的客户信息里有两块：
    subscriber.subscriptions[产品ID]  —— 买过哪些订阅
    subscriber.entitlements[权益名]    —— 解锁了哪些权益
  App 只读这两块来判断是不是 Plus。所以把这两块补上即可，
  不需要动 FotMob 自己的接口（apigw.fotmob.com 的会员字段是服务端同步的，
  路径未知且要登录态，改了反而容易崩）。

为什么同时匹配请求阶段：
  RevenueCat 会带 x-revenuecat-etag 做协商缓存。命中 304 时没有响应体，
  重写脚本拿不到 body 就什么也改不了。所以请求阶段先把这个头删掉，
  强制服务端返回 200 + 完整 JSON。

为什么按 User-Agent 过滤：
  api.revenuecat.com 是全租户共用的域名，很多 App 都用它。
  按 UA 命中 FotMob 才改，其他 App 一律原样放行 —— 否则会把别人的
  订阅状态也一起改坏。

已知边界：
  · 只能解开「客户端判定」的权益（去广告、Plus 专属数据、图表等）。
    需要 FotMob 服务端校验的功能仍然不行，那是账号侧的。
  · 权益名是按社区脚本填的（FotMob+）。若 App 用别的 key，
    这里额外补了几个常见别名，命中任意一个即可。

[rewrite_local]
^https?:\/\/api\.revenuecat\.com\/v1\/subscribers url script-request-header https://dare2live.github.io/rules-hub/qx/rewrites/fotmob-plus.js
^https?:\/\/api\.revenuecat\.com\/v1\/subscribers url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/fotmob-plus.js

[mitm]
hostname = api.revenuecat.com

*************************************/

(function () {
  "use strict";

  var PRODUCT_ID = "fotmob_membership_1y";
  var EXPIRES = "2099-09-09T07:52:54Z";
  var PURCHASED = "2020-02-27T07:52:54Z";
  // 社区脚本用的是 FotMob+；另外几个是各家 App 常见写法，命中任意一个即可。
  var ENTITLEMENT_NAMES = ["FotMob+", "plus", "fotmob_plus", "FotMob Plus"];

  function headerOf(headers, name) {
    if (!headers) return "";
    var want = name.toLowerCase();
    for (var k in headers) {
      if (String(k).toLowerCase() === want) return String(headers[k] || "");
    }
    return "";
  }

  var reqHeaders = (typeof $request !== "undefined" && $request && $request.headers) || {};
  // RevenueCat 的 UA 默认就是宿主 App 的 UA，形如 "FotMob/xxx CFNetwork/... Darwin/..."
  var isFotMob = /fotmob/i.test(headerOf(reqHeaders, "User-Agent"));

  // ---------- 请求阶段：删掉协商缓存头，避免 304 无响应体 ----------
  if (typeof $response === "undefined") {
    if (!isFotMob) {
      $done({});
      return;
    }
    var kept = {};
    for (var k in reqHeaders) {
      if (/etag/i.test(k)) continue;
      kept[k] = reqHeaders[k];
    }
    $done({ headers: kept });
    return;
  }

  // ---------- 响应阶段：注入订阅与权益 ----------
  if (!isFotMob) {
    $done({});
    return;
  }

  var obj;
  try {
    obj = JSON.parse($response.body);
  } catch (e) {
    // 非 JSON（网关错误页 / 空响应）原样放行，不能挂住请求
    $done({});
    return;
  }

  if (!obj || typeof obj !== "object" || !obj.subscriber) {
    $done({});
    return;
  }

  var sub = obj.subscriber;
  if (!sub.subscriptions || typeof sub.subscriptions !== "object") sub.subscriptions = {};
  if (!sub.entitlements || typeof sub.entitlements !== "object") sub.entitlements = {};

  // period_type 必须是 normal：RevenueCat 客户端按它判断"是否为正常订阅"，
  // 写成 active 之类的值反而会被当成未知状态。
  sub.subscriptions[PRODUCT_ID] = {
    billing_issues_detected_at: null,
    expires_date: EXPIRES,
    grace_period_expires_date: null,
    is_sandbox: false,
    original_purchase_date: PURCHASED,
    period_type: "normal",
    purchase_date: PURCHASED,
    store: "app_store",
    unsubscribe_detected_at: null
  };

  for (var i = 0; i < ENTITLEMENT_NAMES.length; i++) {
    sub.entitlements[ENTITLEMENT_NAMES[i]] = {
      expires_date: EXPIRES,
      product_identifier: PRODUCT_ID,
      purchase_date: PURCHASED
    };
  }

  // 有些版本会读 management_url 决定是否显示"管理订阅"，补一个空值避免跳转异常
  if (sub.management_url === undefined) sub.management_url = null;

  $done({ body: JSON.stringify(obj) });
})();
