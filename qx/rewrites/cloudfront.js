/*************************************

项目名称：FT中文网
下载地址：https://t.cn/A6OudTtN
脚本作者：@ddm1023
电报频道：https://t.me/@ddm1023
使用声明：⚠️仅供参考，🈲转载与售卖！

**************************************

[rewrite_local]
^https?:\/\/.*\.cloudfront\.net\/index\.php\/jsapi\/(paywall|get_story_more_info) url script-response-body https://dare2live.github.io/rules-hub/qx/rewrites/cloudfront.js
^https?:\/\/ftmailbox\.cn\/ad_impression\/.+ url reject-200

[mitm]
hostname = *.cloudfront.net, ftmailbox.cn

*************************************/


var ddm = JSON.parse($response.body);

if(/paywall/.test($request.url)){
  Object.assign(ddm, {
    "paywall": 0,
    "premium": 1,
    "expire": "4092599349",
    "standard": 1,
    "v": 2099,
    "campaign_code": "",
    "latest_duration": "yearly",
    "addon": 1
  });
}

if(/get_story_more_info/.test($request.url)){
  ddm.paywall = 0;
  ddm.accessright = "1";
}

$done({ body: JSON.stringify(ddm) });