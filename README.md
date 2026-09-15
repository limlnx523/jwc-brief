# 教务处简报（云端版）

这个目录准备的是 **GitHub Actions 版本**：每天北京时间 **12:30 / 21:30** 由 GitHub 的服务器抓一次
教务处网站，把新文件推送到手机。**不需要你的电脑开机。**

仓库结构：

```
fetch_jwc.py                        抓取脚本（与本地版同一份代码）
state.json                          已读条目基线（必须一起提交，否则第一次会推 1200+ 条历史）
.github/workflows/jwc.yml           定时任务
```

## 一次性配置

1. 建一个**私有**仓库（例如 `jwc-brief`），把本目录三个文件和 workflow 一起推上去。
2. 在仓库 Settings → Secrets and variables → Actions 里加 secret：
   - `JWC_PUSH_TOKEN`：推送渠道的 token（微信 pushplus / Server酱 的 key、Bark 的 key 等）
   - `JWC_PUSH_CHANNEL`（可选）：`pushplus` / `serverchan` / `wecom` / `email` / `ntfy` / `bark`，
     不填默认 `pushplus`
   - 走邮件的话改填 `JWC_MAIL_HOST` / `JWC_MAIL_USER` / `JWC_MAIL_PASS` / `JWC_MAIL_TO`
3. 到 Actions 页面手动点一次 `Run workflow`，确认能收到推送、且 `state.json` 被自动提交。

## 说明

- GitHub 的定时任务用 UTC，并且是**尽力而为**：高峰期可能延后几分钟到一小时，偶尔会漏一次。
  因为脚本是按"和上次状态对比"工作的，漏一次不会丢内容，下次会一起报出来。
- 每次运行都会更新 `state.json` 的 `last_run` 并提交一次，这样仓库一直是活跃的，
  不会被 GitHub 的"60 天无活动自动停用定时任务"规则关掉。
- 云端只能用 secrets 传配置，所以脚本里推送参数的读取顺序是：**环境变量优先，其次 `push_config.json`**。
