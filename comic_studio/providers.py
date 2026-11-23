"""Replace the demo planner, media tools or inspector at the StudioTools boundary."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


class StoryPlanner(Protocol):
    def plan(self, story: str) -> dict: ...


@dataclass(frozen=True)
class MediaRequest:
    task_id: str
    card: dict
    assets: dict  # node id -> {version, data} for each approved visual reference
    feedback: str


class MediaTools(Protocol):
    def keyframe(self, request: MediaRequest) -> dict: ...
    def video(self, request: MediaRequest, frame: dict) -> dict: ...


class Inspector(Protocol):
    def keyframe(self, result: dict, request: MediaRequest) -> list[str]: ...
    def video(self, result: dict, request: MediaRequest, frame: dict) -> list[str]: ...


class DemoPlanner:
    def plan(self, story: str) -> dict:
        parts = [line.strip() for line in story.splitlines() if line.strip()]
        if len(parts) == 1:
            parts = [s.strip() for s in re.split(r"(?<=[。！？.!?])", parts[0]) if s.strip()]
        count = min(6, len(parts))
        if not count:
            raise ValueError("请输入故事原文。")
        beats = []
        scenes = []
        for i in range(count):
            # Keep the entire story when grouping several paragraphs into a single shot.
            action = " ".join(parts[i * len(parts) // count : (i + 1) * len(parts) // count])
            scene_id = f"location{i + 1}"
            scenes.append({"id": scene_id, "name": f"场景 {i + 1}"})
            beats.append({
                "id": f"s{i + 1}", "action": action, "dialogue": "",
                "seconds": 60 // count + int(i < 60 % count),
                "characters": ["lead"], "scene": scene_id,
            })
        return {"characters": [{"id": "lead", "name": "主角"}], "scenes": scenes, "shots": beats}


class DemoMedia:
    def keyframe(self, request: MediaRequest) -> dict:
        return {
            "uri": f"mock://{request.task_id}", "aspect_ratio": "9:16",
            "composition": request.card["action"],
            "asset_versions": {key: asset["version"] for key, asset in request.assets.items()},
        }

    def video(self, request: MediaRequest, frame: dict) -> dict:
        return {
            "uri": f"mock://{request.task_id}", "aspect_ratio": "9:16",
            "source_frame": frame["data"]["uri"], "frame_version": frame["version"],
            "seconds": request.card["seconds"], "subtitle": request.card["dialogue"],
        }


class MetadataInspector:
    def keyframe(self, result: dict, request: MediaRequest) -> list[str]:
        expected = {key: asset["version"] for key, asset in request.assets.items()}
        issues = self._format_issues(result)
        if result.get("asset_versions") != expected:
            issues.append("角色或场景参考版本与镜头卡不一致。")
        return issues

    def video(self, result: dict, request: MediaRequest, frame: dict) -> list[str]:
        issues = self._format_issues(result)
        if (result.get("source_frame"), result.get("frame_version")) != (frame["data"]["uri"], frame["version"]):
            issues.append("视频使用的关键帧与已确认版本不一致。")
        if result.get("seconds") != request.card["seconds"]:
            issues.append("视频时长与镜头卡不一致。")
        if result.get("subtitle") != request.card["dialogue"]:
            issues.append("字幕与镜头卡中的对白不一致。")
        return issues

    @staticmethod
    def _format_issues(result: dict) -> list[str]:
        issues = []
        if not isinstance(result.get("uri"), str) or not result["uri"].strip():
            issues.append("生成工具没有返回素材地址。")
        if result.get("aspect_ratio") != "9:16":
            issues.append("画幅需要为 9:16。")
        return issues


@dataclass
class StudioTools:
    planner: StoryPlanner = field(default_factory=DemoPlanner)
    media: MediaTools = field(default_factory=DemoMedia)
    inspector: Inspector = field(default_factory=MetadataInspector)
