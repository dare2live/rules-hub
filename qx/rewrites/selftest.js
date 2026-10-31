/*
 * Rules Hub 重写自检脚本
 * 只作用于 https://<base_url>/qx/selftest.html
 * 作用：在页面顶部插入一条横幅，证明 MITM 与脚本执行链路是通的
 */
const body = $response.body || "";
const banner = [
  '<div style="position:fixed;top:0;left:0;right:0;z-index:99999;',
  'background:#16a34a;color:#fff;font:600 15px/1.6 -apple-system,sans-serif;',
  'padding:14px 16px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.3)">',
  '✅ 重写已生效（MITM 正常）</div>'
].join("");
let out;
if (body.indexOf("</body>") !== -1) {
  out = body.replace("</body>", banner + "</body>");
} else {
  out = banner + body;
}
$done({ body: out });
