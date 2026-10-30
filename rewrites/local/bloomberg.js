/***********************************

Bloomberg 订阅解锁（Rules Hub 自托管版）

原作者：leepyer（频道 https://t.me/chxm1023）
原地址：https://raw.githubusercontent.com/leey668/pyer/main/bloomberg.js

2026-10 起该仓库已被作者删除（GitHub API 返回 Not Found，名下 20 个仓库里
已无 pyer，也没有任何 fork），原地址变成 404。QX 拉不到脚本时不会报错，
只是重写静默失效——表现就是「规则还在，会员还是没解锁」。

本文件从 Wayback Machine 的 2026-02-12 快照恢复，逻辑与原文一致。

与原版唯一的差异：JSON.parse 外面包了 try/catch。
原版在响应不是 JSON 时（Bloomberg 偶发返回 HTML 错误页）会直接抛异常，
QX 拿到空 body，App 表现为白屏 / 一直转圈。这种「脚本报错把 App 搞崩」
比不去广告难排查得多，所以宁可原样放行。

[rewrite_local]

^https:\/\/mobapi\.bloomberg\.com\/wssmobile\/v1\/user\/subscription url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/bloomberg.js

[mitm]
hostname = mobapi.bloomberg.com

***********************************/

const FAKE_SUBSCRIPTION = [{
    "active": true,
    "product": "BBG",
    "provider": "ZUORA",
    "id": "88888888",
    "subscriptionNumber": "88888888",
    "status": "ACTIVE",
    "endDate": "2099-12-31",
    "startDate": "2024-01-01T00:00:00",
    "entitlements": [{
        "product": "BBG",
        "type": "DIGITAL"
    }],
    "type": "DIGITAL"
}];

if (!$response.body) {
    $done({});
} else {
    try {
        const obj = JSON.parse($response.body);
        obj.subscriptions = FAKE_SUBSCRIPTION;
        $done({ body: JSON.stringify(obj) });
    } catch (e) {
        console.log("Bloomberg 重写：响应不是 JSON，原样放行 -> " + e);
        $done({});
    }
}
