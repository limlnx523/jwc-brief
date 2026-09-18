# -*- coding: utf-8 -*-
"""
浙江师范大学教务处网站 新文件监控 / 简报生成

用法:
    python fetch_jwc.py              正常检查(抓取 -> 对比 -> 写库 -> 推送 -> 打印简报)
    python fetch_jwc.py --baseline   建立/更新基线(把现存条目全部记为已读, 不写库不推送)
    python fetch_jwc.py --dry        只抓取和打印, 不写库不推送
    python fetch_jwc.py --no-push    写库但不推送
    python fetch_jwc.py --days 7     把最近 7 天的条目当成"新"输出(用于补看)

本机网络注意: github 等域名被 hosts 劫持, 且 http_proxy 环境变量是坏的,
因此一律使用 ProxyHandler({}) 绕过代理 + 关闭证书校验。
"""

import io
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape

NL = chr(10)
BASE = "https://jwc.zjnu.edu.cn"
ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state.json")
CONFIG_PATH = os.path.join(ROOT, "push_config.json")
VAULT_DIR = r"F:\Document\Obsidian\University\University\学业规划\教务处简报"

# ---------------------------------------------------------------------------
# 栏目表: (路径, 名称, 是否重点)  重点栏目多翻一页, 防止一天内多条更新被挤掉
# ---------------------------------------------------------------------------
COLUMNS = [
    ("wjtz", "文件通知", True),
    ("gggs", "公告公示", True),
    ("jxdt", "教学动态", False),
    ("xkgl", "选课管理", True),
    ("kktz", "开课通知", True),
    ("ksgl", "考试管理", True),
    ("zzyjzx", "转专业及转学", True),
    ("xjgl", "学籍管理", True),
    ("pkgl", "排课管理", True),
    ("pyfa", "培养方案", True),
    ("zyjs", "专业建设", True),
    ("xfzhrd", "学分转换认定", True),
    ("jsjy", "教师教育", True),
    ("jwgl", "教务管理", False),
    ("zhxx", "综合信息", False),
    ("rcgz", "日常工作", False),
    ("jcjs", "教材建设", False),
    ("jxgg", "教学改革", False),
    ("jxyjyjs", "教学研究与建设", False),
    ("kcjs", "课程建设", False),
    ("jxcg", "教学成果", False),
    ("jxpj", "教学评奖", False),
    ("zsjh", "招生计划", False),
    ("kcsz", "课程思政", False),
    ("jxzlyjk", "教学质量与监控", False),
    ("jxyjkh", "教学业绩考核", False),
    ("ktjxcp", "课堂教学测评", False),
    ("jxdd", "教学督导", False),
    ("jxxxyfk", "教学信息与反馈", False),
    ("cjgl", "成绩管理", False),
    ("dzzc", "电子注册", False),
    ("tjmsyjs", "推荐免试研究生", False),
    ("jsgl", "教室管理", False),
    ("zsbjw2w2w", "专升本及2+2", False),
    ("xwgl", "学位管理", False),
    ("qt", "其它", False),
    ("sjjx", "实践教学", False),
    ("kyxl", "科研训练", False),
    ("syjx", "实验教学", False),
    ("xkjs", "竞赛（A类）", False),
    ("jnjs", "竞赛（B,C类）", False),
    ("cxhd", "双创教育", False),
    ("bysjwlww", "毕业论文", False),
    ("bysx", "实习实训", False),
    ("sxjd", "实习基地", False),
    ("cjrh", "产教融合", False),
    ("jszgrd", "教师资格认定", False),
    ("jysx", "教育三习", False),
    ("jsjyxmyzxdc", "教师教育项目与专项督查", False),
    ("jsjysj", "教师教育数据", False),
    ("jsfzxxgj", "教师发展学校共建", False),
    ("tjjsgzldzgz", "特级教师工作流动站工作", False),
    ("jsjxfzzx_6276", "教师教学发展中心工作", False),
    ("bslc", "办事流程", False),
    ("cxzy", "创先争优", False),
    ("zfjs", "作风建设", False),
    ("jssc", "教师手册", False),
    ("jxtx", "教学通讯", False),
    ("rcgz_4319", "日常工作(旧)", False),
    ("xsxyfz", "学生学业发展", False),
    ("lxgc", "乐学工程", False),
    ("xfjs", "学风建设", False),
    ("zyxz", "资源下载", False),
    ("jxyjyjs_4321", "教学研究与建设(旧)", False),
    ("jxzlyjk_4322", "教学质量与监控(旧)", False),
    ("jwgl_4323", "教务管理(资料)", False),
    ("sjjx_4324", "实践教学(旧)", False),
    ("jsjy_4325", "教师教育(旧)", False),
    ("zhxx_4326", "综合信息(旧)", False),
    ("jsjxfzzx", "教师教学发展中心", False),
    ("jgsz", "机构设置", False),
    ("znjs", "职能介绍", False),
    ("ksfg", "科室分工", False),
    ("glwj", "管理文件", False),
    ("gjwj", "国家文件", False),
    ("sjwj", "省级文件", False),
    ("xjwj", "校级文件", False),
    ("qtwj", "其他文件", False),
    ("bslc_14692", "办事流程(旧)", False),
    ("msxq", "名师详情", False),
]

PRIORITY = dict((slug, pri) for slug, _n, pri in COLUMNS)
HOT_COLUMNS = ("文件通知", "公告公示", "转专业及转学", "选课管理")

# GitHub Actions 的机器是 UTC，简报与时段一律按北京时间算
TZ_CN = timezone(timedelta(hours=8))


def now_cn():
    return datetime.now(TZ_CN)


MORNING_OPEN_H = 9   # 早报最早 09:30 才发
MORNING_OPEN_M = 30
EVENING_OPEN_H = 17  # 晚报最早 17:00 才发


def slot_of(now):
    """返回 (时段唯一标识, 显示名)，按脚本**实际执行的那一刻**判断：
      09:30-17:00  -> 当天早报
      17:00 之后   -> 当天晚报
      00:00-09:30  -> 还属于前一天的晚报（GitHub 把任务拖到凌晨/清晨执行时，
                      不会误发一条“早报”，也不会在清晨打扰用户）
    每个时段只推一次，靠这个标识去重，所以哪个触发点先跑成功就由哪个发。"""
    d = now.strftime("%Y-%m-%d")
    if now.hour >= EVENING_OPEN_H:
        return d + "-evening", "晚报"
    if now.hour < MORNING_OPEN_H or (now.hour == MORNING_OPEN_H and now.minute < MORNING_OPEN_M):
        prev = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return prev + "-evening", "晚报"
    return d + "-morning", "早报"

# 与本人学业规划直接相关的关键词 (命中则放到简报最前面)
KEYWORDS = [
    "转专业", "转学", "选课", "补选", "退课", "退选", "学籍", "学分", "成绩",
    "考试", "等级考试", "四六级", "大学外语", "CET", "期末考试", "缓考", "补考",
    "报名", "培养方案", "排课", "校历", "放假", "实习", "毕业论文", "毕业",
    "竞赛", "数学建模", "蓝桥杯", "创新", "奖学金", "评奖", "评优", "收费", "缴费",
    "分流", "大类", "专业", "辅修", "微专业", "考研", "推免", "免试",
]


def log(msg):
    print(msg, flush=True)


def make_opener():
    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ctx),
    )
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        ("Accept-Language", "zh-CN,zh;q=0.9"),
    ]
    return opener


OPENER = make_opener()


def fetch(url, retries=3, timeout=25, data=None, headers=None):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with OPENER.open(req, timeout=timeout) as r:
                raw = r.read()
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("抓取失败 %s: %s" % (url, last))


LI_RE = re.compile('<li class="list_item[^"]*">(.*?)</li>', re.S)
A_RE = re.compile("<a href='([^']+)'[^>]*title='([^']*)'")
A_FALLBACK_RE = re.compile("<a href='([^']+)'[^>]*>(.*?)</a>", re.S)
DATE_RE = re.compile("Article_PublishDate'>([^<]+)<")
TAG_RE = re.compile("<[^>]+>")


def parse_items(html, column):
    """从列表页提取 (标题, 链接, 日期)。"""
    out = []
    for m in LI_RE.finditer(html):
        chunk = m.group(1)
        a = A_RE.search(chunk)
        if a:
            title = a.group(2)
        else:
            a = A_FALLBACK_RE.search(chunk)
            if not a:
                continue
            title = TAG_RE.sub("", a.group(2))
        href = a.group(1).strip()
        if not href or href.lower().startswith(("javascript:", "#")):
            continue
        d = DATE_RE.search(chunk)
        date = d.group(1).strip() if d else ""
        if len(date) == 5:  # MM-DD, 补全年份
            date = "%d-%s" % (now_cn().year, date)
        if href.startswith("/"):
            href = BASE + href
        title = unescape(" ".join(title.split()))
        if not title:
            continue
        out.append({"title": title, "url": href, "date": date, "column": column})
    seen, uniq = set(), []
    for it in out:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        uniq.append(it)
    return uniq


def crawl_column(slug, name):
    """抓取一个栏目(第一页, 重点栏目或满页时多抓第二页兜底)。"""
    items = []
    page1 = parse_items(fetch("%s/%s/list.htm" % (BASE, slug)), name)
    items.extend(page1)
    if len(page1) >= 14 or PRIORITY.get(slug):
        try:
            items.extend(parse_items(fetch("%s/%s/list2.htm" % (BASE, slug)), name))
        except Exception:
            pass
    return items


def load_json(path, default):
    if os.path.exists(path):
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def is_relevant(item):
    if any(k in item["title"] for k in KEYWORDS):
        return True
    return item["column"] in HOT_COLUMNS


def bullet(item):
    return "- **%s**（%s｜%s）%s%s%s" % (
        item["title"], item["column"], item["date"] or "日期不详", NL, "  ", item["url"])


def join_lines(lines):
    return NL.join(lines)


def build_title(slot_label, new_items, recent):
    """免费推送渠道的卡片只显示标题，所以把最关键那条写进标题（≤ 32 字）。"""
    if new_items:
        prefix = "教务处%s：%d条｜" % (slot_label, len(new_items))
        top = sorted(new_items, key=lambda x: 0 if is_relevant(x) else 1)[0]
        head = top["title"]
    else:
        prefix = "教务处%s：无新增｜" % slot_label
        head = recent[0]["title"] if recent else ""
    budget = 32 - len(prefix)
    if budget <= 0:
        return prefix[:32]
    if len(head) > budget:
        head = head[:budget - 1] + "…"
    return prefix + head


def build_report(new_items, quiet_first_run, total_scanned, recent=None):
    now = now_cn()
    _slot_key, slot = slot_of(now)
    lines = [
        "# 教务处简报 · %s %s" % (now.strftime("%Y-%m-%d"), slot),
        "",
        "抓取时间：%s ｜ 扫描栏目 %d 个" % (now.strftime("%Y-%m-%d %H:%M"), total_scanned),
        "",
    ]
    if quiet_first_run:
        lines += ["**首次运行：已建立基线。**本次不列出历史条目，之后每次只报告新增。", ""]
        return join_lines(lines)
    if not new_items:
        lines += ["**本次没有新增文件 / 通知。**", ""]
        if recent:
            lines += ["最近发布（供参考）：", ""]
            lines += [bullet(i) for i in recent[:5]]
            lines.append("")
        return join_lines(lines)

    hot = [i for i in new_items if is_relevant(i)]
    rest = [i for i in new_items if not is_relevant(i)]
    if hot:
        lines += ["## ⭐ 需要你看一眼", ""]
        lines += [bullet(i) for i in sorted(hot, key=lambda x: x["date"], reverse=True)]
        lines.append("")
    if rest:
        lines += ["## 其他新增", ""]
        lines += [bullet(i) for i in sorted(rest, key=lambda x: x["date"], reverse=True)]
        lines.append("")
    lines += ["合计新增 **%d** 条。" % len(new_items), ""]
    return join_lines(lines)


def write_vault(report):
    if not os.path.isdir(VAULT_DIR):
        os.makedirs(VAULT_DIR)
    now = now_cn()
    day_file = os.path.join(VAULT_DIR, now.strftime("%Y-%m-%d") + ".md")
    if not os.path.exists(day_file):
        head = ["# 教务处简报 %s" % now.strftime("%Y-%m-%d"), "",
                "> 由 Codex 自动生成，每天早/晚各检查一次教务处网站（jwc.zjnu.edu.cn）。", ""]
        with io.open(day_file, "w", encoding="utf-8") as f:
            f.write(join_lines(head))
    with io.open(day_file, "a", encoding="utf-8") as f:
        f.write(NL + "---" + NL + NL + report + NL)
    with io.open(os.path.join(VAULT_DIR, "最新简报.md"), "w", encoding="utf-8") as f:
        f.write(report + NL)
    return day_file


# ---------------------------------------------------------------------------
# 推送
# ---------------------------------------------------------------------------
def get_push_config():
    """推送配置：环境变量优先（云端用 secrets），否则读同目录 push_config.json。"""
    if os.environ.get("JWC_PUSH_CHANNEL"):
        return {"enabled": True, "channel": os.environ["JWC_PUSH_CHANNEL"].strip()}
    return load_json(CONFIG_PATH, {})


def cfg_value(cfg, key, env_key, default=None):
    v = os.environ.get(env_key)
    if v:
        return v
    return cfg.get(key, default)


def push_message(title, body):
    cfg = get_push_config()
    ch = (cfg.get("channel") or "").strip()
    if not ch or not cfg.get("enabled"):
        return "未配置推送渠道(只写入Obsidian库)"
    try:
        if ch == "serverchan":
            data = urllib.parse.urlencode({"title": title, "desp": body}).encode("utf-8")
            resp = fetch("https://sctapi.ftqq.com/%s.send" % cfg_value(cfg, "sendkey", "JWC_PUSH_TOKEN"),
                  data=data,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                jd = json.loads(resp)
            except Exception:
                jd = {}
            if jd.get("code"):
                return "serverchan 返回错误: %s" % json.dumps(jd, ensure_ascii=False)[:200]
            return "已通过 serverchan 推送 (pushid=%s)" % jd.get("data", {}).get("pushid", "?")
        elif ch == "pushplus":
            payload = json.dumps({"token": cfg_value(cfg, "token", "JWC_PUSH_TOKEN"),
                                  "title": title,
                                  "content": body, "template": "markdown"},
                                 ensure_ascii=False).encode("utf-8")
            fetch("https://www.pushplus.plus/send", data=payload,
                  headers={"Content-Type": "application/json"})
        elif ch == "wecom":
            payload = json.dumps({"msgtype": "markdown",
                                  "markdown": {"content": "**%s**" % title + NL + NL + body}},
                                 ensure_ascii=False).encode("utf-8")
            fetch(cfg_value(cfg, "webhook", "JWC_PUSH_WEBHOOK"), data=payload,
                  headers={"Content-Type": "application/json"})
        elif ch == "ntfy":
            server = cfg_value(cfg, "server", "JWC_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
            topic = cfg_value(cfg, "topic", "JWC_NTFY_TOPIC")
            fetch("%s/%s" % (server, topic), data=body.encode("utf-8"),
                  headers={"Title": title.encode("ascii", "ignore").decode() or "jwc",
                           "Markdown": "yes",
                           "Content-Type": "text/markdown; charset=utf-8"})
        elif ch == "bark":
            server = cfg_value(cfg, "server", "JWC_BARK_SERVER", "https://api.day.app").rstrip("/")
            key = cfg_value(cfg, "key", "JWC_BARK_KEY")
            fetch("%s/%s/%s" % (server, key, urllib.parse.quote(title)))
        elif ch == "email":
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(title, "utf-8")
            user = cfg_value(cfg, "user", "JWC_MAIL_USER")
            to = cfg_value(cfg, "to", "JWC_MAIL_TO")
            msg["From"] = user
            msg["To"] = to
            s = smtplib.SMTP_SSL(cfg_value(cfg, "host", "JWC_MAIL_HOST", "smtp.qq.com"),
                                 int(cfg_value(cfg, "port", "JWC_MAIL_PORT", 465)),
                                 timeout=25, context=ssl._create_unverified_context())
            s.login(user, cfg_value(cfg, "password", "JWC_MAIL_PASS"))
            s.sendmail(user, [to], msg.as_string())
            s.quit()
        else:
            return "未知推送渠道: %s" % ch
        return "已通过 %s 推送" % ch
    except Exception as e:  # noqa: BLE001
        return "推送失败(%s): %s" % (ch, e)


def main():
    argv = sys.argv[1:]
    baseline = "--baseline" in argv
    no_push = "--no-push" in argv
    dry = "--dry" in argv
    no_vault = "--no-vault" in argv
    out_path = None
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]
    days = None
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])

    state = load_json(STATE_PATH, {"seen": {}})
    seen = state.get("seen", {})
    seen_titles = state.get("seen_titles", {})
    first_run = len(seen) == 0 and not days

    all_items, errors, ok_columns = [], [], 0
    for slug, name, _pri in COLUMNS:
        try:
            all_items.extend(crawl_column(slug, name))
            ok_columns += 1
        except Exception as e:  # noqa: BLE001
            errors.append("%s(%s): %s" % (name, slug, e))
    log("扫描完成: 成功 %d/%d 个栏目, 取得 %d 条记录" % (ok_columns, len(COLUMNS), len(all_items)))
    for e in errors:
        log("  ! " + e)

    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cand = [i for i in all_items if i["date"] and i["date"] >= cutoff]
    else:
        cand = [i for i in all_items if i["url"] not in seen]

    # 同一篇文章会同时挂在多个栏目下(URL不同), 按 标题+日期 去重, 优先保留重点栏目
    cand.sort(key=lambda x: 0 if x["column"] in HOT_COLUMNS else 1)
    new_items, keys = [], set()
    for i in cand:
        k = i["title"] + "|" + i["date"]
        if k in keys or (k in seen_titles and not days):
            continue
        keys.add(k)
        new_items.append(i)

    for i in all_items:
        seen[i["url"]] = {"title": i["title"], "date": i["date"], "column": i["column"]}
        seen_titles[i["title"] + "|" + i["date"]] = 1
    state["seen"] = seen
    state["seen_titles"] = seen_titles
    state["last_run"] = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    state["columns_ok"] = ok_columns
    save_json(STATE_PATH, state)

    if baseline:
        log("基线已更新: 已记录 %d 条历史条目。" % len(seen))
        return 0

    # 最近发布的条目（本次无新增时也列几条，让人知道监控还活着）
    recent, _rk = [], set()
    for i in sorted(all_items, key=lambda x: x["date"] or "", reverse=True):
        k = i["title"] + "|" + i["date"]
        if k in _rk:
            continue
        _rk.add(k)
        recent.append(i)
        if len(recent) >= 8:
            break

    report = build_report(new_items, first_run, ok_columns, recent)
    if errors:
        report += NL + "⚠️ %d 个栏目抓取失败，下次会自动重试。" % len(errors) + NL
    if not (dry or first_run):
        if out_path:
            with io.open(out_path, "w", encoding="utf-8") as f:
                f.write(report + NL)
            log("简报已写入: %s" % out_path)
        elif not no_vault:
            log("简报已写入: %s" % write_vault(report))
    # 每个时段（早报/晚报）只推一次：GitHub 的定时任务会延迟，同一天可能跑很多次，
    # 靠 state.json 里的 sent_slots 去重，所以哪一次先跑成功就由哪一次发。
    today_key, slot_label = slot_of(now_cn())
    if not (dry or first_run or no_push):
        sent_slots = state.get("sent_slots", {})
        if today_key in sent_slots:
            log("本时段（%s）已经推送过，跳过。" % today_key)
        else:
            res = push_message(build_title(slot_label, new_items, recent), report)
            log(res)
            if not (res.startswith("推送失败") or res.startswith("未配置")):
                sent_slots[today_key] = now_cn().strftime("%H:%M")
                state["sent_slots"] = sent_slots
                save_json(STATE_PATH, state)

    print("")
    print("=" * 60)
    print(report)
    if errors:
        print("异常栏目: %d 个 -> %s" % (len(errors), "; ".join(errors[:5])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
