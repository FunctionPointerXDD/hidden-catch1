from app.worker.geometry import (
    build_rect_tree,
    calculate_overlap_ratio,
    process_rects_with_overlap,
    select_difference_rects,
    shrink_box_centered,
)


def box(x, y, w, h, label="obj", score=0.9):
    return {"x": x, "y": y, "width": w, "height": h, "label": label, "score": score}


def test_overlap_ratio_is_relative_to_child_area():
    child = box(10, 10, 10, 10)
    parent = box(0, 0, 100, 100)
    assert calculate_overlap_ratio(child, parent) == 1.0
    assert calculate_overlap_ratio(parent, child) == 0.01
    assert calculate_overlap_ratio(box(200, 200, 5, 5), parent) == 0.0


def test_rect_tree_nests_contained_rects():
    rects = [box(0, 0, 100, 100), box(10, 10, 20, 20), box(500, 500, 30, 30)]
    roots = build_rect_tree(rects, ["bike", "wheel", "dog"])
    by_label = {node["label"]: node for node in roots}
    assert set(by_label) == {"bike", "dog"}
    assert [c["label"] for c in by_label["bike"]["children"]] == ["wheel"]


def test_shrink_keeps_center():
    shrunk = shrink_box_centered(box(0, 0, 100, 50), 0.1)
    assert shrunk["width"] == 90 and shrunk["height"] == 45
    assert shrunk["x"] + shrunk["width"] / 2 == 50
    assert shrunk["y"] + shrunk["height"] / 2 == 25


def test_partial_overlap_policy():
    a = box(0, 0, 100, 100)
    b = box(50, 0, 100, 100)  # overlaps a by 50% of its own area -> dropped
    c = box(300, 300, 100, 100)
    d = box(380, 300, 100, 100)  # 20% overlap with c -> shrunk
    processed, _ = process_rects_with_overlap([a, b, c, d], ["a", "b", "c", "d"])
    # a is dropped first; b then has no live neighbour left and is kept.
    assert processed[0] is None and processed[1] is not None
    assert processed[2]["width"] == 90 and processed[3]["width"] == 90


def test_select_difference_rects_filters_and_caps():
    width, height = 1000, 1000
    boxes = [
        box(0, 0, 900, 900, "background", 0.99),  # >= 40% of image -> dropped
        box(100, 100, 200, 200, "car", 0.9),  # parent of wheel -> dropped
        box(120, 220, 60, 60, "wheel", 0.8),  # leaf inside car -> kept
        box(700, 700, 5, 5, "speck", 0.95),  # too small -> dropped
        box(600, 100, 150, 150, "tree", 0.7),
        box(100, 600, 150, 150, "dog", 0.6),
        box(400, 400, 100, 100, "cat", 0.5),
        box(800, 400, 100, 100, "bird", 0.4),
    ]
    selected = select_difference_rects(boxes, width, height, max_count=4)
    labels = [r["label"] for r in selected]
    assert labels == ["wheel", "tree", "dog", "cat"]  # score order, capped at 4
    for rect in selected:
        assert rect["x"] >= 0 and rect["y"] >= 0
        assert rect["x"] + rect["width"] <= width
        assert rect["y"] + rect["height"] <= height
        assert isinstance(rect["x"], int)


def test_select_difference_rects_clamps_to_image():
    selected = select_difference_rects(
        [box(-20, 950, 100, 100, "edge", 0.9)], 1000, 1000, min_area_ratio=0.0
    )
    assert selected == [
        {"x": 0, "y": 950, "width": 80, "height": 50, "label": "edge", "score": 0.9}
    ]


def test_select_difference_rects_handles_empty():
    assert select_difference_rects([], 100, 100) == []
    assert select_difference_rects([box(0, 0, 10, 10)], 0, 0) == []
