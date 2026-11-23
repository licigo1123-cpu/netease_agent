import copy
import unittest

from comic_studio.providers import DemoMedia, StudioTools
from comic_studio.workflow import (WorkflowError, create_project, edit, export_manifest,
                                   generate, inspect, review)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.p = create_project("一封信", "阿遥走入店铺。\n阿遥来到站台。")

    def finish(self):
        for key in inspect(self.p):
            node = inspect(self.p)[key]
            if node.state == "approved":
                continue
            if node.state != "review":
                generate(self.p, key)
            review(self.p, key, "approved")

    def stop_before(self, target):
        for key, node in inspect(self.p).items():
            if key == target:
                return
            if not node.current:
                generate(self.p, key)
            review(self.p, key, "approved")
        self.fail("Unknown target")

    def test_final_review_gates_ordered_timeline(self):
        with self.assertRaises(WorkflowError):
            generate(self.p, "clip:s1")
        self.stop_before("timeline")
        generate(self.p, "timeline")
        with self.assertRaises(WorkflowError):
            export_manifest(self.p)
        review(self.p, "timeline", "approved")
        timeline = export_manifest(self.p)
        self.assertEqual((timeline["aspect_ratio"], timeline["duration_s"]), ("9:16", 60))
        self.assertEqual([(s["shot_id"], s["start_s"], s["end_s"]) for s in timeline["segments"]],
                         [("s1", 0, 30), ("s2", 30, 60)])

    def test_video_rework_reuses_exact_approved_frame(self):
        self.finish()
        before = copy.deepcopy(self.p["versions"])
        review(self.p, "clip:s1", "rejected", "转头时变脸，只重做动作。")
        generate(self.p, "clip:s1")
        version = inspect(self.p)["clip:s1"].current
        self.assertEqual(version["data"]["source_frame"], before["frame:s1"][-1]["data"]["uri"])
        self.assertEqual(version["sources"]["frame:s1"], 1)
        self.assertIn("变脸", version["feedback"])
        for key in ("frame:s1", "frame:s2", "clip:s2"):
            self.assertEqual(self.p["versions"][key], before[key])
        self.assertEqual(inspect(self.p)["clip:s1"].state, "review")
        with self.assertRaises(WorkflowError):
            export_manifest(self.p)

    def test_bad_keyframe_found_in_clip_routes_to_image_tool(self):
        self.finish()
        review(self.p, "clip:s1", "rejected", "首帧服装画错。", target="frame")
        self.assertEqual(inspect(self.p)["frame:s1"].state, "rejected")
        with self.assertRaises(WorkflowError):
            generate(self.p, "clip:s1")
        generate(self.p, "frame:s1")
        self.assertEqual(inspect(self.p)["frame:s1"].current["feedback"], "首帧服装画错。")
        with self.assertRaises(WorkflowError):
            generate(self.p, "clip:s1")
        review(self.p, "frame:s1", "approved")
        generate(self.p, "clip:s1")
        self.assertEqual(inspect(self.p)["clip:s1"].current["data"]["frame_version"], 2)
        self.assertEqual(inspect(self.p)["clip:s2"].state, "approved")

    def test_scene_revision_only_marks_referencing_shot_and_keeps_edited_dialogue(self):
        self.stop_before("board:s1")
        generate(self.p, "board:s1")
        card = inspect(self.p)["board:s1"].current["data"].copy()
        edit(self.p, "board:s1", {**card, "dialogue": "我来了。"})
        self.finish()
        second_clip = copy.deepcopy(self.p["versions"]["clip:s2"])
        key = "scene:location1"
        scene = inspect(self.p)[key].current["data"]
        edit(self.p, key, {**scene, "description": "雨夜，冷色台灯。"})
        states = inspect(self.p)
        for affected in ("board:s1", "frame:s1", "clip:s1", "timeline"):
            self.assertEqual(states[affected].state, "stale")
        for unaffected in ("board:s2", "frame:s2", "clip:s2", "character:lead"):
            self.assertEqual(states[unaffected].state, "approved")
        self.finish()
        self.assertEqual(self.p["versions"]["clip:s2"], second_clip)
        self.assertEqual(inspect(self.p)["frame:s1"].current["data"]["asset_versions"][key], 2)
        self.assertEqual(export_manifest(self.p)["segments"][0]["subtitle"], "我来了。")

    def test_shared_character_revision_is_seen_by_both_shots(self):
        self.finish()
        role = inspect(self.p)["character:lead"].current["data"]
        edit(self.p, "character:lead", {**role, "description": "短发，穿黄色雨衣。"})
        states = inspect(self.p)
        self.assertEqual([states[k].state for k in ("clip:s1", "clip:s2")], ["stale", "stale"])
        self.assertEqual(states["scene:location1"].state, "approved")

    def test_qc_blocks_bad_assets_and_duration(self):
        class BrokenMedia(DemoMedia):
            def keyframe(self, request):
                return {**super().keyframe(request), "asset_versions": {}}

            def video(self, request, frame):
                return {**super().video(request, frame), "seconds": 1}

        tools = StudioTools(media=BrokenMedia())
        self.stop_before("frame:s1")
        generate(self.p, "frame:s1", tools)
        self.assertEqual(inspect(self.p)["frame:s1"].state, "qc_failed")
        with self.assertRaises(WorkflowError):
            review(self.p, "frame:s1", "approved")
        generate(self.p, "frame:s1")
        review(self.p, "frame:s1", "approved")
        generate(self.p, "clip:s1", tools)
        self.assertIn("时长", inspect(self.p)["clip:s1"].current["issues"][0])
        with self.assertRaises(WorkflowError):
            review(self.p, "clip:s1", "approved")
        generate(self.p, "clip:s1")
        review(self.p, "clip:s1", "approved")
        self.assertEqual(inspect(self.p)["clip:s1"].current["sources"]["frame:s1"], 2)

    def test_failed_provider_attempt_can_resume(self):
        class UnavailableMedia(DemoMedia):
            def keyframe(self, request):
                raise TimeoutError("演示超时")

        self.stop_before("frame:s1")
        generate(self.p, "frame:s1", StudioTools(media=UnavailableMedia()))
        self.assertEqual(inspect(self.p)["frame:s1"].state, "failed")
        generate(self.p, "frame:s1")
        attempts = self.p["versions"]["frame:s1"]
        self.assertEqual([v["task"]["status"] for v in attempts], ["failed", "succeeded"])
        self.assertNotEqual(attempts[0]["task"]["id"], attempts[1]["task"]["id"])

    def test_script_validation_and_reordered_shots(self):
        self.finish()
        script = copy.deepcopy(inspect(self.p)["script"].current["data"])
        script["shots"].reverse()
        invalid = copy.deepcopy(script)
        invalid["shots"][0]["scene"] = "missing"
        with self.assertRaises(ValueError):
            edit(self.p, "script", invalid)
        self.assertEqual(inspect(self.p)["timeline"].state, "approved")
        edit(self.p, "script", script)
        self.finish()
        self.assertEqual([s["shot_id"] for s in export_manifest(self.p)["segments"]], ["s2", "s1"])
