"""Validate editable drafts before they enter the version graph."""
import re


def text_field(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空。")


def shot_card(data):
    text_field(data.get("action"), "镜头动作")
    if type(data.get("seconds")) is not int or data["seconds"] <= 0:
        raise ValueError("镜头时长必须是正整数。")
    if not isinstance(data.get("dialogue"), str):
        raise ValueError("对白需要使用文本，可留空。")


def identifiers(rows, label):
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{label}需要使用对象列表。")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key) for key in ids):
        raise ValueError(f"{label} ID 只接受字母、数字、下划线和短横线。")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{label} ID 必须唯一。")
    return set(ids)


def validate(kind, data):
    if not isinstance(data, dict):
        raise ValueError("草稿需要是一个 JSON 对象。")
    if kind == "script":
        roles = identifiers(data.get("characters"), "角色")
        scenes = identifiers(data.get("scenes"), "场景")
        if not identifiers(data.get("shots"), "镜头"):
            raise ValueError("剧本至少需要一个镜头。")
        for row in data["characters"] + data["scenes"]:
            text_field(row.get("name"), "名称")
        for shot in data["shots"]:
            shot_card(shot)
            cast = shot.get("characters")
            if (not isinstance(cast, list)
                    or not all(isinstance(key, str) and key in roles for key in cast)
                    or len(set(cast)) != len(cast)):
                raise ValueError("镜头的角色引用无效或重复。")
            if not isinstance(shot.get("scene"), str) or shot["scene"] not in scenes:
                raise ValueError("镜头引用的场景不存在。")
    elif kind in {"character", "scene"}:
        text_field(data.get("name"), "名称")
        text_field(data.get("description"), "视觉设定")
        refs = data.get("references")
        if not isinstance(refs, list) or not refs:
            raise ValueError("至少保留一个参考图地址。")
        for ref in refs:
            text_field(ref, "参考图地址")
    elif kind == "board":
        shot_card(data)
