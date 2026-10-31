Rules Hub - 软路由规则订阅
生成时间: 2026-10-31 18:00:35 (北京时间)
订阅根地址: https://dare2live.github.io/rules-hub/router/fancyss

chnroute.txt      中国 IP 段 3886 条（旧版 7456 行 / ipset 7464 条）
gfwlist.conf      代理域名 4424 条（旧版 2015-08-01，11166 行）
cdn.txt           国内 CDN 域名 109695 条（旧版 2015-08-01，73483 行）
version1          fancyss 原生更新清单
merlin_blacklist.txt  强制代理域名 382 条
merlin_whitelist.txt  强制直连域名 218 条

安装（路由器 SSH 执行）:
  wget -qO- https://dare2live.github.io/rules-hub/router/install.sh | sh

安装后行为:
  - 立即同步一次（chnroute / gfwlist / cdn 三个文件）
  - 每周日 04:10 自动同步（cru 定时任务，开机自动恢复）
  - 自动备份原文件为 *.orig / *.bak，可随时回滚
  - 条目数异常、下载到 HTML、md5 未变化时都不会覆盖
  - 主源失败自动回退备用源: https://cdn.jsdelivr.net/gh/dare2live/rules-hub@gh-pages

回滚:
  cp /koolshare/ss/rules/chnroute.txt.orig /koolshare/ss/rules/chnroute.txt
  cp /koolshare/ss/rules/gfwlist.conf.orig /koolshare/ss/rules/gfwlist.conf
  cp /koolshare/ss/rules/cdn.txt.orig /koolshare/ss/rules/cdn.txt
  sh /koolshare/ss/ssconfig.sh restart
