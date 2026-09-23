"""Pure rectangle logic used to turn detected objects into puzzle answers.

Everything here works on plain dicts ``{"x", "y", "width", "height"}`` in
pixel units so it can be unit-tested without images or network access.
"""

from __future__ import annotations

from typing import Any

Rect = dict[str, float]


def calculate_overlap_ratio(child_box: Rect, parent_box: Rect) -> float:
    """Return how much of ``child_box`` lies inside ``parent_box`` (0.0-1.0)."""
    x1, y1 = child_box["x"], child_box["y"]
    x2 = x1 + child_box["width"]
    y2 = y1 + child_box["height"]

    px1, py1 = parent_box["x"], parent_box["y"]
    px2 = px1 + parent_box["width"]
    py2 = py1 + parent_box["height"]

    inter_x1 = max(x1, px1)
    inter_y1 = max(y1, py1)
    inter_x2 = min(x2, px2)
    inter_y2 = min(y2, py2)

    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0

    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    child_area = child_box["width"] * child_box["height"]
    if child_area <= 0:
        return 0.0
    return inter_area / child_area


def build_rect_tree(
    rects: list[Rect], labels: list[str], overlap_threshold: float = 0.9
) -> list[dict]:
    """Build a containment forest: a rect is a child of the smallest larger rect
    that contains at least ``overlap_threshold`` of its area."""
    rect_data: list[tuple[Rect, str, float, int]] = []
    for i, (rect, label) in enumerate(zip(rects, labels)):
        rect_data.append((rect, label, rect["width"] * rect["height"], i))
    rect_data.sort(key=lambda item: item[2], reverse=True)

    nodes: list[dict] = []
    node_map: dict[int, dict] = {}
    for rect, label, _area, original_index in rect_data:
        node = {
            "rect": rect,
            "label": label,
            "index": original_index,
            "children": [],
            "parent": None,
        }
        nodes.append(node)
        node_map[original_index] = node

    for i, (rect, _label, _area, original_index) in enumerate(rect_data):
        current_node = node_map[original_index]
        best_parent = None
        best_parent_area = float("inf")
        for j in range(i):  # only larger rects can be parents
            parent_rect, _pl, parent_area, parent_index = rect_data[j]
            parent_node = node_map[parent_index]
            if parent_node["parent"] is not None:
                continue
            if calculate_overlap_ratio(rect, parent_rect) >= overlap_threshold:
                if parent_area < best_parent_area:
                    best_parent = parent_node
                    best_parent_area = parent_area
        if best_parent is not None:
            best_parent["children"].append(current_node)
            current_node["parent"] = best_parent

    return [node for node in nodes if node["parent"] is None]


def shrink_box_centered(box: Rect, shrink_ratio: float = 0.1) -> Rect:
    """Shrink a box around its center by ``shrink_ratio``."""
    center_x = box["x"] + box["width"] / 2
    center_y = box["y"] + box["height"] / 2
    new_width = box["width"] * (1 - shrink_ratio)
    new_height = box["height"] * (1 - shrink_ratio)
    return {
        "x": center_x - new_width / 2,
        "y": center_y - new_height / 2,
        "width": new_width,
        "height": new_height,
    }


def process_rects_with_overlap(
    rects: list[Rect], labels: list[str]
) -> tuple[list[Rect | None], list[str]]:
    """Resolve partially overlapping rects.

    For each rect the largest overlap with any other rect (relative to its own
    area) decides its fate: >= 50% -> dropped (``None``), 10-50% -> shrunk by
    10% around its center, < 10% -> kept as is.
    """
    processed: list[Rect | None] = [dict(rect) for rect in rects]
    for i, current in enumerate(processed):
        if current is None:
            continue
        max_overlap = 0.0
        for j, other in enumerate(processed):
            if i == j or other is None:
                continue
            max_overlap = max(max_overlap, calculate_overlap_ratio(current, other))
        if max_overlap >= 0.5:
            processed[i] = None
        elif max_overlap >= 0.1:
            processed[i] = shrink_box_centered(current, shrink_ratio=0.1)
    return processed, list(labels)


def clamp_rect(rect: Rect, image_width: int, image_height: int) -> dict[str, int]:
    """Round a rect to integer pixels and clamp it to the image bounds."""
    x1 = max(0, int(round(rect["x"])))
    y1 = max(0, int(round(rect["y"])))
    x2 = min(image_width, int(round(rect["x"] + rect["width"])))
    y2 = min(image_height, int(round(rect["y"] + rect["height"])))
    return {"x": x1, "y": y1, "width": max(0, x2 - x1), "height": max(0, y2 - y1)}


def _filter_by_size(
    boxes: list[dict[str, Any]],
    total_area: float,
    max_area_ratio: float,
    min_area_ratio: float,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for box in boxes:
        if box["width"] <= 0 or box["height"] <= 0:
            continue
        area_ratio = (box["width"] * box["height"]) / total_area
        if min_area_ratio <= area_ratio < max_area_ratio:
            kept.append(box)
    return kept


def _leaf_indices(rects: list[Rect], labels: list[str], threshold: float) -> list[int]:
    """Indices of rects that do not contain any other rect."""
    excluded: set[int] = set()

    def mark_parents(node: dict) -> None:
        if node["children"]:
            excluded.add(node["index"])
            for child in node["children"]:
                mark_parents(child)

    for root in build_rect_tree(rects, labels, threshold):
        mark_parents(root)
    return [i for i in range(len(rects)) if i not in excluded]


def select_difference_rects(
    boxes: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    *,
    max_count: int = 5,
    max_area_ratio: float = 0.4,
    min_area_ratio: float = 0.003,
    containment_threshold: float = 0.9,
) -> list[dict[str, Any]]:
    """Turn raw detections into the final list of regions to edit.

    ``boxes`` are ``{"label", "score", "x", "y", "width", "height"}`` in pixels.
    Steps (same policy as the original pipeline, plus a minimum size and a cap):
      1. drop rects covering >= ``max_area_ratio`` of the image (backgrounds)
         or < ``min_area_ratio`` (unclickable / unreliable to edit),
      2. drop rects that contain other rects (keep the leaf objects),
      3. resolve partial overlaps (drop / shrink),
      4. keep at most ``max_count`` rects, highest detection score first.
    """
    if image_width <= 0 or image_height <= 0:
        return []
    ordered = sorted(boxes, key=lambda b: float(b.get("score", 0.0)), reverse=True)
    sized = _filter_by_size(
        ordered, float(image_width * image_height), max_area_ratio, min_area_ratio
    )
    if not sized:
        return []

    rects: list[Rect] = [
        {"x": b["x"], "y": b["y"], "width": b["width"], "height": b["height"]}
        for b in sized
    ]
    labels = [str(b.get("label") or "object") for b in sized]
    leaves = _leaf_indices(rects, labels, containment_threshold)
    processed, _ = process_rects_with_overlap(
        [rects[i] for i in leaves], [labels[i] for i in leaves]
    )

    selected: list[dict[str, Any]] = []
    for original_index, rect in zip(leaves, processed):
        if rect is None:
            continue
        clamped = clamp_rect(rect, image_width, image_height)
        if clamped["width"] <= 0 or clamped["height"] <= 0:
            continue
        source = sized[original_index]
        selected.append(
            {
                **clamped,
                "label": str(source.get("label") or "object"),
                "score": float(source.get("score", 0.0)),
            }
        )
        if len(selected) >= max_count:
            break
    return selected
