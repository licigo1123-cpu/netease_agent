"""Small server-rendered workbench; all state transitions live in workflow.py."""
import json
from html import escape
from urllib.parse import urlencode

from .workflow import EDITABLE, inspect


def h(value):
    return escape(str(value), quote=True)


GROUPS = [
    ("剧本", {"script"}), ("角色与场景", {"character", "scene"}), ("分镜", {"board"}),
    ("关键帧", {"frame"}), ("镜头视频", {"clip"}), ("时间线", {"timeline"}),
]
STATES = {
    "ready": "待生成", "blocked": "等待上游", "stale": "需复核", "review": "待确认",
    "approved": "已确认", "rejected": "待返工", "qc_failed": "质检未过", "failed": "任务失败",
}
SAMPLE = "阿遥在修表铺里收到一封寄给明天的信。\n她追到站台，发现邮差正等着她。\n阿遥打开信封，里面是一张回家的车票。"


def page(title, content):
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{h(title)} · 漫剧工作台</title><link rel="stylesheet" href="/studio.css"></head>
<body><header><div class="wrap"><a href="/" class="brand">漫剧工作台</a><span>9:16 竖屏制作</span></div></header>
<main class="wrap">{content}</main></body></html>"""


def home(projects):
    links = "".join(f'<li><a href="/projects/{h(key)}">{h(name)}</a></li>' for key, name in projects)
    return page("项目", f"""<h1>创作项目</h1><div class="home-grid"><section><h2>新建一集</h2>
<form action="/projects" method="post"><label>片名<input name="title" required value="明天的来信"></label>
<label>故事原文<textarea name="story" rows="7" required>{h(SAMPLE)}</textarea></label>
<button>拆成分场剧本</button></form></section><section><h2>继续创作</h2>
{f'<ul>{links}</ul>' if links else '<p>新建项目后，可在这里继续上次的审核。</p>'}
<p class="muted">本地演示使用模拟生成工具。终审后可下载含字幕和素材版本的剪辑清单。</p></section></div>""")


def field(label, name, value, area=False, numeric=False):
    if area:
        control = f'<textarea name="{name}" rows="3">{h(value)}</textarea>'
    else:
        attrs = 'type="number" min="1" required' if numeric else 'type="text" required'
        control = f'<input {attrs} name="{name}" value="{h(value)}">'
    return f'<label>{h(label)}{control}</label>'


def editor(step, data, form):
    if step.kind == "script":
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        controls = field("分场剧本 JSON", "payload", pretty, area=True)
    elif step.kind == "board":
        controls = (field("动作与构图", "action", data["action"], area=True)
                    + field("字幕或对白", "dialogue", data["dialogue"], area=True)
                    + field("时长（秒）", "seconds", data["seconds"], numeric=True))
    else:
        controls = (field("名称", "name", data["name"])
                    + field("视觉设定", "description", data["description"], area=True)
                    + field("参考图地址（每行一个）", "references", "\n".join(data["references"]), area=True))
    return (f'<details><summary>编辑并保存新版本</summary>{form}{controls}'
            '<button name="op" value="edit">保存草稿</button></form></details>')


def preview(view):
    step, current = view.step, view.current
    if not current or current["task"]["status"] == "failed":
        return ""
    data = current["data"]
    if step.kind == "script":
        lines = "".join(f'<li><strong>{h(s["action"])}</strong><small>{s["seconds"]} 秒'
                        f'　{h(s["dialogue"])}</small></li>' for s in data["shots"])
        return f'<ol class="script">{lines}</ol>'
    if step.kind in {"character", "scene"}:
        refs = "".join(f'<li><code>{h(uri)}</code></li>' for uri in data["references"])
        return f'<h3>{h(data["name"])}</h3><p>{h(data["description"])}</p><details><summary>参考图地址</summary><ul>{refs}</ul></details>'
    if step.kind == "board":
        return f'<blockquote>{h(data["action"])}</blockquote><p>{data["seconds"]} 秒 · 对白　{h(data["dialogue"]) or "无"}</p>'
    if step.kind == "frame":
        return f'<blockquote>{h(data.get("composition", ""))}</blockquote><p>关键帧占位预览 · {h(data.get("aspect_ratio", "待检查"))}</p>'
    if step.kind == "clip":
        return (f'<h3>镜头视频占位预览</h3><p>{h(data.get("seconds", "—"))} 秒 · '
                f'关键帧 v{h(data.get("frame_version", "—"))} · {h(data.get("aspect_ratio", "—"))}</p>'
                f'<blockquote>{h(data.get("subtitle", "")) or "本镜无对白"}</blockquote>')
    rows = "".join(f'<tr><td>{h(s["shot_id"])}</td><td>{s["start_s"]}–{s["end_s"]} 秒</td>'
                   f'<td>v{s["clip_version"]}</td><td>{h(s["subtitle"]) or "—"}</td></tr>' for s in data["segments"])
    return (f'<p>{data["duration_s"]} 秒 · {h(data["aspect_ratio"])}</p><table><thead><tr>'
            f'<th>镜头</th><th>时间段</th><th>视频版本</th><th>字幕</th></tr></thead><tbody>{rows}</tbody></table>')


def project_page(project, revision, selected=None):
    nodes = inspect(project)
    if selected not in nodes:
        selected = next((key for key, v in nodes.items() if v.ready and v.state != "approved"), "timeline")
    view = nodes[selected]
    base = "/projects/" + project["id"]
    def link(key):
        return base + "?" + urlencode({"step": key})
    menu = []
    for title, kinds in GROUPS:
        items = []
        for key, v in nodes.items():
            if v.step.kind in kinds:
                active = ' aria-current="step"' if key == selected else ""
                items.append(f'<a href="{link(key)}"{active}><span>{h(v.step.title)}</span>'
                             f'<small class="{v.state}">{STATES[v.state]}</small></a>')
        menu.append(f'<h3>{title}</h3>' + "".join(items))
    version = view.current
    form = (f'<form method="post" action="{base}/action"><input type="hidden" name="step" value="{h(selected)}">'
            f'<input type="hidden" name="revision" value="{revision}">')
    actions = []
    if not view.ready:
        missing = [f'<a href="{link(k)}">{h(nodes[k].step.title)}</a>' for k in view.step.requires if nodes[k].state != "approved"]
        actions.append('<p>请先确认 ' + "、".join(missing) + '。</p>')
    elif view.state in {"ready", "stale", "failed", "qc_failed", "rejected"}:
        actions.append(form + '<button name="op" value="generate">生成新版本</button></form>')
    if view.state == "review":
        actions.append(form + '<button name="op" value="approve">确认此版本并继续</button></form>')
    if version and view.ready and view.step.kind in EDITABLE:
        actions.append(editor(view.step, version["data"], form))
    if view.state in {"review", "approved", "qc_failed"}:
        specific = ('<button name="op" value="reject_frame">关键帧画错，退回出图</button>'
                    if view.step.kind == "clip" else "")
        text = "复用确认帧，重做本镜视频" if view.step.kind == "clip" else "退回此版本"
        actions.append(f'<details><summary>退回返工</summary>{form}<label>原因<textarea name="note" required rows="2"></textarea></label>'
                       f'<div class="buttons"><button name="op" value="reject">{text}</button>{specific}</div></form></details>')
    if selected == "timeline" and view.state == "approved":
        actions.append(f'<a class="button" href="{base}/timeline.json">下载剪辑清单</a>')
    warnings = "".join(f'<p class="issue">{h(issue)}</p>' for issue in (version or {}).get("issues", []))
    if view.state == "stale":
        warnings += '<p class="issue">上游版本已变更，此稿需要按最新定稿重新生成或复核。</p>'
    if version and version["sources"]:
        refs = "、".join(f'<a href="{link(k)}">{h(nodes[k].step.title)} v{n}</a>'
                       if k in nodes else h(k) + f' v{n}' for k, n in version["sources"].items())
        sources = f'<p class="muted">本稿依据　{refs}</p>'
    else:
        sources = ""
    history = []
    for old in reversed(project["versions"].get(selected, [])):
        decisions = " / ".join(STATES[r["decision"]] + (" · " + h(r["note"]) if r["note"] else "")
                               for r in old["reviews"])
        details = decisions or ("质检未过" if old["issues"] else "已生成草稿")
        if old["task"]["status"] == "failed":
            details = "任务失败"
        history.append(f'<li><b>v{old["version"]}</b>　{details}<small>{h(old["created_at"])} · {h(old["task"]["id"])}</small></li>')
    approved = sum(v.state == "approved" for v in nodes.values())
    label = f' v{version["version"]}' if version else ""
    main = (f'<a href="/">所有项目</a><h1>{h(project["title"])}</h1><p class="muted">{approved} / {len(nodes)} 项已确认 · 本地模拟生成</p>'
            f'<div class="layout"><nav aria-label="制作步骤">{"".join(menu)}</nav><section><div class="stage">'
            f'<h2>{h(view.step.title)}{label}</h2><span class="{view.state}">{STATES[view.state]}</span></div>'
            f'{warnings}{preview(view)}{sources}<div class="actions">{"".join(actions)}</div>'
            f'<details><summary>任务与审核记录（{len(history)}）</summary><ul>{"".join(history)}</ul></details>'
            f'<details><summary>故事原文</summary><p class="story">{h(project["story"])}</p></details></section></div>')
    return page(project["title"], main)
