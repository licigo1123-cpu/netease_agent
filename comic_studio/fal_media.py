"""fal.ai image and image-to-video adapters for the local workbench."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .providers import DemoPlanner


class FilmPlanner(DemoPlanner):
    def plan(self, story):
        script = super().plan(story)
        beats = script["shots"]
        shots = []
        for i in range(6):
            index = i * len(beats) // 6
            shot = dict(beats[index], id=f"s{i + 1}", seconds=10)
            if i and index == (i - 1) * len(beats) // 6:
                shot["action"] += " 用不同景别表现同一动作的细节。"
            shots.append(shot)
        script["shots"] = shots
        return script


class FalMedia:
    label = "fal.ai 真实生成"

    def __init__(self, key):
        self.key = key

    def run(self, model, payload):
        request = Request("https://fal.run/" + model, data=json.dumps(payload).encode(),
                          headers={"Authorization": "Key " + self.key, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=900) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(f"fal.ai 请求失败（HTTP {exc.code}），请检查密钥、余额及输入素材。") from exc
        except (TimeoutError, URLError) as exc:
            raise ValueError("fal.ai 连接超时或中断，请先在服务商记录中查看任务结果。") from exc

    @staticmethod
    def url(result, field):
        item = result.get(field) if isinstance(result, dict) else None
        if isinstance(item, list):
            item = item[0] if item else None
        url = item.get("url") if isinstance(item, dict) else None
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("服务商没有返回有效的媒体地址。")
        return url

    def reference_image(self, kind, data, story):
        subject = "同一个角色的正面、侧面设定图，保持服装一致" if kind == "character" else "场景环境设定图"
        result = self.run("fal-ai/flux/schnell", {
            "prompt": f"漫画风格，{subject}。{data['name']}。{data['description']}。故事背景：{story}",
            "image_size": "portrait_16_9"})
        return self.url(result, "images")

    def keyframe(self, request):
        refs, anchors = [], []
        for asset in request.assets.values():
            data = asset["data"]
            links = [url for url in data["references"] if url.startswith("https://")]
            if not links:
                raise ValueError(f"请在「{data['name']}」粘贴 HTTPS 参考图并重新确认，再生成关键帧。")
            refs.extend(links)
            anchors.append(data["name"] + "：" + data["description"])
        prompt = "竖屏漫画关键帧。保持参考角色、服装和环境一致。" + " ".join(anchors)
        result = self.run("fal-ai/flux-pro/kontext/max/multi", {
            "prompt": prompt + "。" + request.card["action"] + " " + request.feedback,
            "image_urls": refs, "aspect_ratio": "9:16"})
        return {"uri": self.url(result, "images"), "aspect_ratio": "9:16",
                "composition": request.card["action"],
                "asset_versions": {k: v["version"] for k, v in request.assets.items()}}

    def video(self, request, frame):
        image = frame["data"]["uri"]
        seconds = request.card["seconds"]
        if not image.startswith("https://"):
            raise ValueError("请先生成并确认真实关键帧。")
        if seconds not in (5, 10):
            raise ValueError("请将分镜时长改为 5 或 10 秒，并重新确认分镜及关键帧。")
        result = self.run("fal-ai/kling-video/v2.1/standard/image-to-video", {
            "image_url": image, "duration": str(seconds),
            "prompt": request.card["action"] + " 保持角色外观一致。" + request.feedback})
        return {"uri": self.url(result, "video"), "source_frame": image, "frame_version": frame["version"],
                "aspect_ratio": "9:16", "seconds": seconds, "subtitle": request.card["dialogue"]}
