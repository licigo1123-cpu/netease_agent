"""Compose the ordered edit list from reviewed clip versions."""


def compose(shots: list[dict], clips: dict) -> dict:
    position = 0
    segments = []
    for shot in shots:
        key = "clip:" + shot["id"]
        ref = clips[key]
        clip = ref["data"]
        end = position + clip["seconds"]
        segments.append({
            "shot_id": shot["id"], "start_s": position, "end_s": end,
            "clip": clip["uri"], "clip_version": ref["version"],
            "source_frame": clip["source_frame"], "frame_version": clip["frame_version"],
            "subtitle": clip["subtitle"],
        })
        position = end
    return {"aspect_ratio": "9:16", "duration_s": position, "segments": segments}
