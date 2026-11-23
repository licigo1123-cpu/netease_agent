import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from comic_studio.store import Conflict, ProjectStore
from comic_studio.web import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "projects.sqlite3"
        self.store = ProjectStore(self.path)
        self.app = create_app(self.store)

    def request(self, path, fields=None):
        route, _, query = path.partition("?")
        env = {}
        setup_testing_defaults(env)
        body = urlencode(fields or {}).encode()
        env.update(PATH_INFO=route, QUERY_STRING=query, REQUEST_METHOD="GET" if fields is None else "POST",
                   CONTENT_LENGTH=str(len(body)))
        env["wsgi.input"] = io.BytesIO(body)
        response = []
        def start_response(status, headers):
            response.extend((status, dict(headers)))
        data = b"".join(self.app(env, start_response)).decode()
        return response[0], response[1], data

    def start_project(self):
        status, headers, _ = self.request("/projects", {"title": "短篇", "story": "她打开信封。"})
        self.assertTrue(status.startswith("303"))
        return headers["Location"]

    def submit(self, path, key, op, **fields):
        screen = self.request(path + "?" + urlencode({"step": key}))[2]
        rev = re.search(r'name="revision" value="([0-9]+)"', screen).group(1)
        return self.request(path + "/action", {"revision": rev, "step": key, "op": op, **fields})

    def test_web_flow_and_resume(self):
        self.assertIn("新建一集", self.request("/")[2])
        path = self.start_project()
        self.assertIn("剧本", self.request(path)[2])
        self.assertEqual(self.request(path + "/timeline.json")[0][:3], "409")
        for key in ("script", "character:lead", "scene:location1", "board:s1", "frame:s1", "clip:s1", "timeline"):
            if key != "script":
                self.assertEqual(self.submit(path, key, "generate")[0][:3], "303")
            if key == "board:s1":
                self.assertEqual(self.submit(path, key, "edit", action="打开信封", dialogue="明天见。", seconds="60")[0][:3], "303")
            self.assertEqual(self.submit(path, key, "approve")[0][:3], "303")
        self.app = create_app(ProjectStore(self.path))
        self.assertIn("下载剪辑清单", self.request(path)[2])
        status, headers, data = self.request(path + "/timeline.json")
        self.assertEqual(status[:3], "200")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(json.loads(data)["segments"][0]["subtitle"], "明天见。")

    def test_stale_tab_and_concurrent_save(self):
        path = self.start_project()
        pid = path.rsplit("/", 1)[1]
        old, rev = self.store.load(pid)
        fields = {"revision": rev, "step": "script", "op": "approve"}
        self.assertEqual(self.request(path + "/action", fields)[0][:3], "303")
        self.assertEqual(self.request(path + "/action", fields)[0][:3], "409")
        with self.assertRaises(Conflict):
            self.store.save(old, rev)
        self.assertEqual(len(self.store.load(pid)[0]["versions"]["script"][0]["reviews"]), 1)

    def test_invalid_forms_do_not_commit(self):
        self.assertEqual(self.request("/projects", {"title": "空", "story": " "})[0][:3], "400")
        path = self.start_project()
        self.assertEqual(self.submit(path, "script", "edit", payload="{}")[0][:3], "400")
        self.assertEqual(self.store.load(path.rsplit("/", 1)[1])[1], 1)
