"""WSGI entry point for the local creator workbench."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from . import workbench
from .providers import StudioTools
from .store import Conflict
from .workflow import WorkflowError, create_project, edit, export_manifest, generate, lookup, review

PROJECT = re.compile(r"/projects/([a-f0-9]{32})(/action|/timeline\.json)?")
CSS = Path(__file__).with_name("studio.css")


def parse_form(environ):
    size = int(environ.get("CONTENT_LENGTH") or 0)
    if not 0 <= size <= 1_000_000:
        raise ValueError("表单过大。")
    return {k: v[0] for k, v in parse_qs(
        environ["wsgi.input"].read(size).decode("utf-8"), keep_blank_values=True).items()}


def edited_data(kind, form):
    if kind == "script":
        return json.loads(form.get("payload", ""))
    if kind == "board":
        return {"action": form.get("action", ""), "seconds": int(form.get("seconds", "")),
                "dialogue": form.get("dialogue", "")}
    if kind in {"character", "scene"}:
        return {"name": form.get("name", ""), "description": form.get("description", ""),
                "references": [s.strip() for s in form.get("references", "").splitlines() if s.strip()]}
    raise WorkflowError("此步骤需通过返工修改。")


def create_app(store, tools=None):
    tools = tools or StudioTools()
    mode = getattr(tools.media, "label", "本地模拟生成")

    def app(env, start_response):
        def reply(status, body="", kind="text/html; charset=utf-8", headers=()):
            data = body.encode("utf-8")
            start_response(status, [("Content-Type", kind), ("Content-Length", str(len(data))),
                                    ("Cache-Control", "no-store"), *headers])
            return [data]

        def redirect(location):
            return reply("303 See Other", headers=[("Location", location)])

        def error(status, message, back="/"):
            body = f'<h1>{workbench.h(message)}</h1><a href="{workbench.h(back)}">返回工作台</a>'
            return reply(status, workbench.page("请求提示", body))

        path, method = env["PATH_INFO"], env["REQUEST_METHOD"]
        back = "/"
        try:
            if (method, path) == ("GET", "/studio.css"):
                return reply("200 OK", CSS.read_text(encoding="utf-8"), "text/css; charset=utf-8")
            if (method, path) == ("GET", "/"):
                return reply("200 OK", workbench.home(store.list_projects(), mode))
            if (method, path) == ("POST", "/projects"):
                form = parse_form(env)
                project = create_project(form.get("title", ""), form.get("story", ""), tools)
                store.add(project)
                return redirect("/projects/" + project["id"])
            match = PROJECT.fullmatch(path)
            if not match:
                return error("404 Not Found", "页面不存在。")
            pid, endpoint = match.groups()
            try:
                project, revision = store.load(pid)
            except KeyError:
                return error("404 Not Found", "项目不存在。")
            back = "/projects/" + pid
            if method == "GET" and not endpoint:
                selected = parse_qs(env.get("QUERY_STRING", "")).get("step", [None])[0]
                return reply("200 OK", workbench.project_page(project, revision, selected, mode))
            if method == "GET" and endpoint == "/timeline.json":
                output = json.dumps(export_manifest(project), ensure_ascii=False, indent=2)
                return reply("200 OK", output, "application/json; charset=utf-8",
                             [("Content-Disposition", 'attachment; filename="timeline.json"')])
            if method != "POST" or endpoint != "/action":
                return error("405 Method Not Allowed", "请求方式不适用于此步骤。", back)
            form = parse_form(env)
            if int(form.get("revision", "-1")) != revision:
                raise Conflict("项目已有新版本，请返回并刷新后再操作。")
            key, op = form.get("step", ""), form.get("op", "")
            view = lookup(project, key)
            destination = key
            if op == "generate":
                generate(project, key, tools)
            elif op == "edit":
                edit(project, key, edited_data(view.step.kind, form))
            elif op == "approve":
                review(project, key, "approved")
                destination = None
            elif op in {"reject", "reject_frame"}:
                target = "frame" if op == "reject_frame" else "self"
                review(project, key, "rejected", form.get("note", ""), target)
                if target == "frame":
                    destination = view.step.requires[0]
            else:
                raise WorkflowError("未知操作。")
            store.save(project, revision)
            return redirect(back + ("?" + urlencode({"step": destination}) if destination else ""))
        except (Conflict, WorkflowError) as exc:
            return error("409 Conflict", str(exc), back)
        except ValueError as exc:
            return error("400 Bad Request", str(exc), back)

    return app
