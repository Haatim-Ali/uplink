"""Photo reading: several readings of one photo are combined safely. No model or network needed:
the model is replaced with canned answers.

Run:  python tests/test_vision.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
import vision  # noqa: E402


def answer(n, name="bagels", unit="bagel", conf="high", allergens=("gluten",), cold=False, low=None):
    return {"is_food": True, "groups": [{"name": name, "unit": unit, "count_low": low if low is not None else n,
                                         "count_high": n, "how_counted": "rows"}],
            "category": "packaged", "needs_cold": cold, "allergens": list(allergens), "allergens_uncertain": False,
            "confidence": conf, "notes": ""}


def fake(replies, half_replies=()):
    """Make the model return these answers in order (an Exception instance means that call fails).
    Prompts for half a photo get their answers from half_replies, since they run at the same time as re-reads."""
    queue, halves_queue = list(replies), list(half_replies)
    calls = []

    def chat_json(system, user, **kw):
        calls.append(user)
        r = (halves_queue if "half of a larger photo" in user else queue).pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    llm.available, llm.chat_json, llm.provider = (lambda: True), chat_json, (lambda: "test")
    return calls


def photo(w=800, h=600):
    out = io.BytesIO()
    vision.Image.new("RGB", (w, h), "white").save(out, "JPEG")
    return out.getvalue()


def read(replies, reads=3, split_min=20, w=800, h=600, halves=()):
    vision.VISION_READS, vision.VISION_SPLIT_MIN = reads, split_min
    calls = fake(replies, halves)
    food, src = vision.analyze(photo(w, h))
    return food, src, calls


def test_a_sure_first_reading_costs_one_call():
    food, src, calls = read([answer(12)])
    g = food["groups"][0]
    assert (g["count_low"], g["count_high"], food["confidence"], src, len(calls)) == (12, 12, "high", "test", 1)


def test_an_unsure_first_reading_is_read_again():
    food, _, calls = read([answer(12, conf="medium"), answer(12), answer(12)])
    assert len(calls) == 3 and food["groups"][0]["count_high"] == 12 and "they agree" in food["notes"]


def test_a_failed_first_reading_is_read_again():
    food, src, calls = read([RuntimeError("timeout"), answer(8), answer(8)])
    assert len(calls) == 3 and src == "test" and food["groups"][0]["count_high"] == 8


def test_disagreeing_readings_widen_the_range_and_lower_confidence():
    food, _, _ = read([answer(10, conf="medium"), answer(12), answer(14)])
    g = food["groups"][0]
    assert (g["count_low"], g["count_high"], g["count"]) == (10, 14, 12)   # covers every reading; best = middle
    assert food["confidence"] == "low" and "please check" in food["notes"]


def test_a_small_disagreement_means_medium_confidence():
    food, _, _ = read([answer(20, conf="medium"), answer(20), answer(21)], split_min=999)
    assert food["confidence"] == "medium"
    assert food["groups"][0]["count_high"] == 21


def test_allergens_and_cold_are_combined_on_the_safe_side():
    food, _, _ = read([answer(6, conf="low"), answer(6, allergens=("gluten", "sesame")), answer(6, cold=True)])
    assert food["allergens"] == ["gluten", "sesame"] and food["needs_cold"]


def test_all_failed_readings_give_an_empty_form_never_fake_food():
    food, src, _ = read([RuntimeError("down")] * 3)
    assert src == "fallback" and food["items"] == []


def test_not_food_on_the_first_reading_stops_there():
    food, src, calls = read([{"is_food": False, "notes": "a cat"}])
    assert src == "fallback" and "doesn't look like food" in food["notes"] and len(calls) == 1


def test_big_spreads_are_also_counted_in_halves():
    # 3 full readings say 30; the two halves up close say 14 + 20 = 34
    food, _, calls = read([answer(30)] * 3, split_min=20, halves=[answer(14), answer(20)])
    assert len(calls) == 5 and any("left half" in c for c in calls) and any("right half" in c for c in calls)
    g = food["groups"][0]
    assert (g["count_low"], g["count_high"]) == (30, 34) and food["confidence"] == "low"
    assert "halves counted up close: 34" in food["notes"]


def test_tall_photos_are_cut_top_and_bottom():
    _, _, calls = read([answer(25)] * 3, split_min=20, w=600, h=900, halves=[answer(12), answer(13)])
    assert any("top half" in c for c in calls) and any("bottom half" in c for c in calls)


def test_small_unsure_spreads_skip_the_halves():
    _, _, calls = read([answer(6, conf="medium")] * 3, split_min=20)
    assert len(calls) == 3


def test_a_single_reading_still_works():
    food, _, calls = read([answer(9, conf="medium")], reads=1)   # VISION_READS=1: never re-read
    assert len(calls) == 1 and food["confidence"] == "medium" and food["groups"][0]["count_high"] == 9


def test_servings_come_from_the_middle_reading_weight_from_the_range():
    food, _, _ = read([answer(8, conf="medium"), answer(9), answer(10)], split_min=999)
    assert food["servings"] == 9 and food["weight_lbs"] == [2.0, 2.5]   # bagels: 1 serving, 0.25 lb each


def test_an_outlier_reading_lowers_confidence_but_not_the_range():
    food, _, _ = read([answer(9, conf="medium"), answer(20), answer(20)], split_min=999)
    g = food["groups"][0]
    assert (g["count_low"], g["count_high"], g["count"]) == (20, 20, 20)
    assert food["confidence"] == "low" and "please check" in food["notes"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"\n{len(tests)} tests passed")
