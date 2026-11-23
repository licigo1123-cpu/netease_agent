import unittest
from unittest.mock import Mock

from comic_studio.fal_media import FalMedia, FilmPlanner
from comic_studio.providers import MediaRequest
from comic_studio.workflow import create_project, generate, inspect, review
from comic_studio.providers import StudioTools
from comic_studio.workbench import preview


class FalTests(unittest.TestCase):
    def test_real_mode_pipeline(self):
        media = FalMedia("test")
        def reply(model, payload):
            if "kling" in model:
                self.assertEqual(payload["image_url"], "https://example.org/frame.png")
                self.assertEqual(payload["duration"], "10")
                return {"video": {"url": "https://example.org/clip.mp4"}}
            if "kontext" in model:
                self.assertTrue(payload["image_urls"])
                name = "frame"
            else:
                name = "reference"
            return {"images": [{"url": f"https://example.org/{name}.png"}]}
        media.run = Mock(side_effect=reply)
        tools = StudioTools(planner=FilmPlanner(), media=media)
        project = create_project("短篇", "她打开信。", tools)
        for key in inspect(project):
            if key != "script":
                generate(project, key, tools)
            review(project, key, "approved")
            if key == "clip:s1":
                self.assertIn("<video", preview(inspect(project)[key]))
                self.assertIn("<img", preview(inspect(project)["frame:s1"]))
                break
        self.assertEqual(inspect(project)["clip:s1"].state, "approved")

    def test_invalid_duration_before_submission(self):
        media = FalMedia("test")
        media.run = Mock()
        request = MediaRequest("job", {"seconds": 20}, {}, "")
        with self.assertRaisesRegex(ValueError, "时长"):
            media.video(request, {"data": {"uri": "https://example.org/image.png"}})
        media.run.assert_not_called()
