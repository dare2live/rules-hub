/*************************************

项目名称：有谱么（本地维护版）
上游参考：chxm1023/Rewrite（2025-01-10）、Guding88/Script（数据来自 @Baby）
维护原因：
  1. chxm1023 版只补 level / isMember / adsDisabled / adsDisabledTill 四个字段，
     而社区另有版本还带 ladder="member"。App 若按 ladder 判断会员等级，
     只改四个字段就会出现「头像框是会员、权益没解锁」。
  2. 原脚本没有 try/catch，接口返回非 JSON（网关错误页 / 空响应）时
     JSON.parse 抛异常、拿不到 $done，QX 请求会挂到超时 —— 表现为页面一直转圈。
  3. 不整包替换响应（Guding88 版是直接伪造整个 user info，会丢真实字段），
     只覆盖会员态，其余字段保留服务端返回值。

[rewrite_local]
^https?:\/\/yopu\.co\/api\/user\/info url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/youpume.v2.js

[mitm]
hostname = yopu.co

*************************************/

(function () {
  var obj;
  try {
    obj = JSON.parse($response.body);
  } catch (e) {
    // 非 JSON（错误页 / 空响应 / 未登录）：原样放行，绝不把请求挂死
    return $done({});
  }
  if (!obj || typeof obj !== "object") {
    return $done({});
  }
  obj.level = 1;
  obj.isMember = true;
  obj.adsDisabled = true;
  obj.adsDisabledTill = 4092599349000;
  obj.ladder = "member";
  $done({ body: JSON.stringify(obj) });
})();
