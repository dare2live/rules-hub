# 分流规则体检报告

> 生成时间：2026-11-03 20:38（北京时间）
> 工具：`scripts/rules_lint.py`（只读，不改任何规则）
> 检查对象：`dist/qx/*.list`，即真正下发给设备的规则表

按客户端真实匹配顺序（`filter_local` 内联 → `filter_remote` 顺序 → geoip → final）逐条推演，找出「写了但永远不生效」的规则。

## 一、总览

| 规则源 | 规则数 | 被遮蔽 | 其中策略冲突 |
|---|---:|---:|---:|
| unbreak（内联 filter_local） | 33 | 0 | 0 |
| adblock_cn | 15 | 0 | 0 |
| claude | 6 | 0 | 0 |
| google_ai | 29 | 1 | 0 |
| workbuddy_cn | 16 | 0 | 0 |
| workbuddy | 8 | 0 | 0 |
| media | 255 | 2 | 0 |
| openai | 33 | 0 | 0 |
| tiktok | 34 | 1 | 0 |
| proxy | 38 | 0 | 0 |
| custom_direct | 183 | 2 | 0 |
| reject | 290 | 58 | 57 |

合计：940 条，被遮蔽 **64** 条，其中会改变走向的 **57** 条。

## 二、会改变走向的遮蔽（要决策）

| 域名 | 本应走 | 实际走 | 被哪条挡住 |
|---|---|---|---|
| `log.byteoversea.com` | REJECT | Proxy | `DOMAIN-SUFFIX,byteoversea.com`（tiktok） |
| `-tracker.biliapi.net` | REJECT | DIRECT | `DOMAIN-SUFFIX,biliapi.net`（custom_direct） |
| `_vmind.qqvideo.tc.qq.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,qq.com`（custom_direct） |
| `ad.ixigua.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,ixigua.com`（custom_direct） |
| `a3.bytecdn.cn` | REJECT | DIRECT | `DOMAIN-SUFFIX,bytecdn.cn`（custom_direct） |
| `a3.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `ad.toutiao.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,toutiao.com`（custom_direct） |
| `adash.man.aliyuncs.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,aliyuncs.com`（custom_direct） |
| `adp.atm.youku.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,youku.com`（custom_direct） |
| `adsfilebssdlbig.ali.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `adshare.toutiao.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,toutiao.com`（custom_direct） |
| `android.bugly.qq.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,qq.com`（custom_direct） |
| `apiinit.amap.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,amap.com`（custom_direct） |
| `bds.snssdk.com` | REJECT | Proxy | `DOMAIN-SUFFIX,snssdk.com`（tiktok） |
| `bdsp.x.jd.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,jd.com`（custom_direct） |
| `c1img.ali.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `caclick.baidu.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,baidu.com`（custom_direct） |
| `count.atm.youku.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,youku.com`（custom_direct） |
| `cpu.baidu.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,baidu.com`（custom_direct） |
| `dm.bytedance.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,bytedance.com`（custom_direct） |
| `dm.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `dm.toutiao.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,toutiao.com`（custom_direct） |
| `ems.youku.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,youku.com`（custom_direct） |
| `extlog.snssdk.com` | REJECT | Proxy | `DOMAIN-SUFFIX,snssdk.com`（tiktok） |
| `fans.m.tmall.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,tmall.com`（custom_direct） |
| `kepler.jd.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,jd.com`（custom_direct） |
| `keplerapi.jd.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,jd.com`（custom_direct） |
| `kgipadstat.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `kgipadstatbak.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `kgstaticdlbssdlbig.tx.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `logwebs.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `m.atm.youku.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,youku.com`（custom_direct） |
| `m.suning.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,suning.com`（custom_direct） |
| `mapi.m.jd.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,jd.com`（custom_direct） |
| `mobilead.kuwo.cn` | REJECT | DIRECT | `DOMAIN-SUFFIX,kuwo.cn`（custom_direct） |
| `nbcollect.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `nbcollectretry.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `p3-pack.byteimg.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,byteimg.com`（custom_direct） |
| `p3.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `p6-pack.byteimg.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,byteimg.com`（custom_direct） |
| `policy.jd.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,jd.com`（custom_direct） |
| `rich.kuwo.cn` | REJECT | DIRECT | `DOMAIN-SUFFIX,kuwo.cn`（custom_direct） |
| `rt-m.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `rtmretry.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `s1.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `s2.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `s3.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `s3a.pstatp.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,pstatp.com`（custom_direct） |
| `sdfp.snssdk.com` | REJECT | Proxy | `DOMAIN-SUFFIX,snssdk.com`（tiktok） |
| `searchrecommend.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `splashimgbssdl.yun.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `tracker.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `trackercdnbj.kugou.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,kugou.com`（custom_direct） |
| `tunion-api.m.taobao.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,taobao.com`（custom_direct） |
| `val.atm.youku.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,youku.com`（custom_direct） |
| `wgo.mmstat.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,mmstat.com`（custom_direct） |
| `ynuf.alipay.com` | REJECT | DIRECT | `DOMAIN-SUFFIX,alipay.com`（custom_direct） |

## 三、防误杀白名单的预期覆盖（设计如此，不用改）

没有。

## 四、同策略冗余（行为无变化，可清理）

### media（2 条）

- `DOMAIN-KEYWORD,youtube` ← 被 `DOMAIN-SUFFIX,youtube`（media）覆盖
- `DOMAIN-SUFFIX,netflix.com.edgesuite.net` ← 被 `DOMAIN,netflix.com.edgesuite.net`（media）覆盖

### custom_direct（2 条）

- `DOMAIN-SUFFIX,work.weixin.qq.com` ← 被 `DOMAIN-SUFFIX,weixin.qq.com`（custom_direct）覆盖
- `DOMAIN-SUFFIX,qyapi.weixin.qq.com` ← 被 `DOMAIN-SUFFIX,weixin.qq.com`（custom_direct）覆盖

### google_ai（1 条）

- `DOMAIN,makersuite.google.com` ← 被 `DOMAIN-SUFFIX,makersuite.google.com`（google_ai）覆盖

### tiktok（1 条）

- `DOMAIN-KEYWORD,musical.ly` ← 被 `DOMAIN-SUFFIX,musical.ly`（tiktok）覆盖

### reject（1 条）

- `DOMAIN-KEYWORD,mobads.baidu.com` ← 被 `DOMAIN-SUFFIX,mobads.baidu.com`（adblock_cn）覆盖

## 五、同一文件内的重复条目

没有。

