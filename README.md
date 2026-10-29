# 🚀 Rules Hub - 多端统一规则与托管中心

专为 **Surge 5 (Mac/iOS)**、**Quantumult X (iOS)**、**Shadowrocket (小火箭)** 及 **华硕梅林软路由 (Shadowsocks)** 打造的跨端、多协议统一规则托管与自动化编译系统。

---

## 🌟 核心特性

1. **单一数据源维护 (Single Source of Truth)**：
   只需在 `config.yaml` 或 `rules/` 中维护一套规则，自动编译输出适配所有客户端的专属格式。
2. **纯规则解耦，零节点泄露**：
   本仓库及托管链接**绝不包含任何私密节点 IP、密码或密钥**，公开发布 100% 安全。
3. **彻底根治规则冲突与锁区**：
   - `Claude`：物理绑定新加坡专线（HY2 优先，SS 备用）。
   - `GoogleAI`：锁定美区与新加坡（Gemini、Antigravity、Cloud Code），坚决规避香港节点封锁。
   - `WorkBuddy`：腾讯 WorkBuddy / CodeBuddy AI 加速通道。
   - `DIRECT`：微信、企业微信、钉钉、国内银行、个人服务器无损直连。
4. **全 Serverless 零服务器成本**：
   基于 GitHub Actions + Cloudflare Pages，全球 CDN 毫秒级分发，永远在线，永不宕机。

---

## 📁 目录结构

```text
rules-hub/
├── config.yaml                    # 全局配置中心（策略组映射、规则源）
├── rules/                         # 原子纯净规则源（纯域名与IP）
│   ├── claude.txt                 # Claude 专属清单
│   ├── google-ai.txt              # Gemini / Antigravity / 遥测清单
│   ├── workbuddy.txt              # 腾讯 WorkBuddy 清单
│   ├── direct.txt                 # 微信 / 企微 / 钉钉 / 国内银行
│   ├── media.txt                  # YouTube / Netflix / Spotify
│   ├── reject.txt                 # 广告拦截
│   └── unbreak.txt                # 防误杀白名单
├── generator/
│   └── build.py                   # Python 3 转换编译引擎
├── web/
│   └── index.html                 # 现代化 Web 仪表盘
├── .github/workflows/
│   └── deploy.yml                 # Actions CI/CD 自动部署至 Cloudflare Pages
└── dist/                          # 编译生成的成品 (Surge / QX / 小火箭 / 软路由)
```

---

## 🛠 本地快速构建

```bash
# 运行编译引擎
python3 generator/build.py
```
编译完成后将在 `dist/` 目录下生成：
- `dist/surge/profile.conf`：Surge 完整托管配置
- `dist/qx/profile.conf`：Quantumult X 完整配置（参考墨鱼标准模块化结构）
- `dist/router/merlin_blacklist.txt`：梅林软路由 SS 插件自定义黑名单域名
- `dist/router/merlin_whitelist.txt`：梅林软路由 SS 插件自定义白名单域名
- `dist/web/index.html`：Cloudflare Pages 静态主页
