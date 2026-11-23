"""Versioned approval graph shared by the workbench and alternative clients."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from .providers import MediaRequest, StudioTools
from .timeline import compose
from .validation import text_field, validate


class WorkflowError(ValueError):
    """The requested transition is unavailable for the current versions."""


EDITABLE = {"script", "character", "scene", "board"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Step:
    key: str
    kind: str
    title: str
    requires: tuple[str, ...] = ()
    seed: dict = field(default_factory=dict)


@dataclass
class View:
    step: Step
    state: str
    ready: bool
    current: dict | None
    pins: dict


def create_project(title, story, tools=None):
    text_field(title, "片名")
    text_field(story, "原文")
    project = {"id": uuid4().hex, "title": title.strip(), "story": story.strip(), "versions": {}}
    generate(project, "script", tools or StudioTools())
    return project


def graph(project):
    steps = [Step("script", "script", "分场剧本")]
    history = project["versions"].get("script", [])
    if not history:
        return steps
    script = history[-1]["data"]
    for kind, rows in (("character", script["characters"]), ("scene", script["scenes"])):
        for row in rows:
            key = kind + ":" + row["id"]
            drafts = project["versions"].get(key, [])
            name = drafts[-1]["data"]["name"] if drafts else row["name"]
            steps.append(Step(key, kind, name, ("script",), row))
    clip_keys = []
    for index, shot in enumerate(script["shots"], 1):
        suffix = ":" + shot["id"]
        refs = tuple("character:" + key for key in shot["characters"]) + ("scene:" + shot["scene"],)
        board, frame, clip = "board" + suffix, "frame" + suffix, "clip" + suffix
        steps.extend([
            Step(board, "board", f"镜头 {index} · 分镜", ("script", *refs), shot),
            Step(frame, "frame", f"镜头 {index} · 关键帧", (board, *refs)),
            Step(clip, "clip", f"镜头 {index} · 视频", (frame, board)),
        ])
        clip_keys.append(clip)
    steps.append(Step("timeline", "timeline", "成片时间线", tuple(clip_keys), script))
    return steps


def inspect(project):
    """Evaluate parents first so stale approvals propagate through the affected branch."""
    result = {}
    for step in graph(project):
        versions = project["versions"].get(step.key, [])
        current = versions[-1] if versions else None
        ready = all(result[key].state == "approved" for key in step.requires)
        pins = {key: result[key].current["version"] for key in step.requires if result[key].current}
        if current is None:
            state = "ready" if ready else "blocked"
        elif not ready or current["sources"] != pins:
            state = "stale"
        elif current["task"]["status"] == "failed":
            state = "failed"
        elif current["issues"] and not current["reviews"]:
            state = "qc_failed"
        elif current["reviews"]:
            state = current["reviews"][-1]["decision"]
        else:
            state = "review"
        result[step.key] = View(step, state, ready, current, pins)
    return result


def lookup(project, key):
    view = inspect(project).get(key)
    if view is None:
        raise WorkflowError("当前剧本中没有这个步骤。")
    return view


def append_version(project, view, data, issues, task, feedback=""):
    versions = project["versions"].setdefault(view.step.key, [])
    versions.append({
        "version": len(versions) + 1, "sources": dict(view.pins), "data": deepcopy(data),
        "issues": list(issues), "task": task, "feedback": feedback, "reviews": [], "created_at": now(),
    })


def reference(project, key, version):
    return {"version": version, "data": deepcopy(project["versions"][key][version - 1]["data"])}


def references(project, pins):
    return {key: reference(project, key, version) for key, version in pins.items()}


def generate(project, key, tools=None):
    tools = tools or StudioTools()
    view = lookup(project, key)
    step = view.step
    if not view.ready or view.state not in {"ready", "stale", "failed", "qc_failed", "rejected"}:
        raise WorkflowError("请先确认依赖版本，再生成或返工当前步骤。")
    number = len(project["versions"].get(key, [])) + 1
    task_id = f"{project['id']}/{key.replace(':', '/')}/v{number}"
    task = {"id": task_id, "status": "succeeded", "origin": "generator"}
    feedback = ""
    if view.current:
        reviews = view.current["reviews"]
        if reviews and reviews[-1]["decision"] == "rejected":
            feedback = reviews[-1]["note"]
        elif view.current["issues"]:
            feedback = " ".join(view.current["issues"])
    issues = []
    if step.kind == "script":
        data = tools.planner.plan(project["story"])
    elif step.kind in {"character", "scene"}:
        angles = ["front", "profile", "three-quarter"] if step.kind == "character" else ["setting"]
        data = {
            "name": step.seed["name"],
            "description": "待定稿的外貌与服装" if step.kind == "character" else "待定稿的空间与光线",
            "references": [f"mock://{task_id}/{angle}" for angle in angles],
        }
    elif step.kind == "board":
        data = {name: step.seed[name] for name in ("action", "dialogue", "seconds")}
        if view.current and view.current["sources"]["script"] == view.pins["script"]:
            data = view.current["data"]  # Refresh visual references without losing the editor's copy.
    elif step.kind in {"frame", "clip"}:
        shot_id = key.split(":", 1)[1]
        board_key = "board:" + shot_id
        board = project["versions"][board_key][view.pins[board_key] - 1]
        assets = {k: v for k, v in board["sources"].items() if k.startswith(("character:", "scene:"))}
        request = MediaRequest(task_id, deepcopy(board["data"]), references(project, assets), feedback)
        try:
            if step.kind == "frame":
                data = tools.media.keyframe(request)
                if not isinstance(data, dict):
                    raise ValueError("图片工具返回了无效的素材记录。")
                issues = tools.inspector.keyframe(data, request)
            else:
                frame_key = "frame:" + shot_id
                frame = reference(project, frame_key, view.pins[frame_key])
                data = tools.media.video(request, frame)
                if not isinstance(data, dict):
                    raise ValueError("视频工具返回了无效的素材记录。")
                issues = tools.inspector.video(data, request, frame)
        except (OSError, RuntimeError, ValueError) as error:
            task["status"] = "failed"
            data, issues = {}, [f"生成工具失败：{error}"]
    else:
        data = compose(step.seed["shots"], references(project, view.pins))
    if step.kind in EDITABLE:
        validate(step.kind, data)
    append_version(project, view, data, issues, task, feedback)


def edit(project, key, data):
    view = lookup(project, key)
    if view.step.kind not in EDITABLE or not view.ready or not view.current:
        raise WorkflowError("当前步骤尚不可编辑。")
    validate(view.step.kind, data)
    if view.current["data"] == data and view.state not in {"stale", "rejected"}:
        raise WorkflowError("草稿内容没有变化。")
    task = {"id": uuid4().hex, "status": "succeeded", "origin": "editor"}
    append_version(project, view, data, [], task)


def review(project, key, decision, note="", target="self"):
    view = lookup(project, key)
    if decision == "approved":
        if view.state != "review" or target != "self":
            raise WorkflowError("只能确认质检通过且依赖版本有效的待审稿。")
    elif decision == "rejected":
        if view.state not in {"approved", "review", "qc_failed"}:
            raise WorkflowError("此版本尚不可退回。")
        text_field(note, "返工原因")
        if target not in {"self", "frame"} or (target == "frame" and view.step.kind != "clip"):
            raise WorkflowError("返工目标无效。")
    else:
        raise WorkflowError("未知审核操作。")
    record = {"decision": decision, "note": note.strip(), "at": now(), "target": target}
    view.current["reviews"].append(record)
    if target == "frame":
        # The clip pins the exact frame being revoked; another shot never shares its frame node.
        frame_key = view.step.requires[0]
        version = view.current["sources"][frame_key]
        frame = project["versions"][frame_key][version - 1]
        frame["reviews"].append({**record, "from": key})


def export_manifest(project):
    view = lookup(project, "timeline")
    if view.state != "approved":
        raise WorkflowError("全部镜头及当前时间线终审通过后才能导出。")
    return {
        "project": project["title"], "timeline_version": view.current["version"],
        "format": "edit-decision-list", **deepcopy(view.current["data"]),
    }
