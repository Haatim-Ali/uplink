"""Measure how well the vision model reads real food photos.

Put photos in a folder with an answers.csv next to them:

    file,item,count
    bagels1.jpg,bagel,12
    pizza_box.jpg,pizza,16       <- count in the unit you'd naturally count (slices here)
    sushi.jpg,sushi|nigiri|maki,20   <- several accepted names, separated by |

Then, with the model connected (scripts/start_vision.sh + source scripts/vision_env.sh):

    python scripts/vision_eval.py eval_photos/ [results.csv]

It prints what the model said for each photo and a summary you can quote:
how often it named the right food, how often the true count fell inside its range,
and the average counting error.
"""
import csv
import mimetypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
import vision  # noqa: E402


def main(folder, out=None):
    if not llm.available():
        sys.exit("No model connected. Run scripts/start_vision.sh, then: source scripts/vision_env.sh")
    with open(os.path.join(folder, "answers.csv")) as f:
        rows = list(csv.DictReader(f))
    named = in_range = close = 0
    errors, times, results = [], [], []
    for row in rows:
        path = os.path.join(folder, row["file"])
        media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            start = time.time()
            food, source = vision.analyze(f.read(), media_type)
            times.append(time.time() - start)
        names, want = row["item"].lower().split("|"), float(row["count"])
        want_item = names[0]
        groups = [g for g in food.get("groups", [])
                  if any(n in g["name"].lower() or n in g["unit"] for n in names)]
        lo = sum(g["count_low"] for g in groups)
        hi = sum(g["count_high"] for g in groups)
        ok_name = bool(groups)
        ok_range = ok_name and lo <= want <= hi
        named += ok_name
        in_range += ok_range
        best = sum(g.get("count", (g["count_low"] + g["count_high"]) / 2) for g in groups)
        err = abs(best - want) / want if ok_name else None
        if ok_name:
            errors.append(err)
            close += err <= 0.1
        results.append({"file": row["file"], "want": want, "said": "; ".join(food["items"]), "low": lo, "high": hi,
                        "named": ok_name, "in_range": ok_range, "error": None if err is None else round(err, 3),
                        "confidence": food.get("confidence"), "seconds": round(times[-1], 1)})
        said = ", ".join(food["items"]) or "(nothing)"
        got = f"{lo}-{hi}" if lo != hi else str(lo)
        print(f"{row['file']:<22} want {want_item} x{want:g} | said: {said[:40]:<40} count {got if ok_name else '-':<7} "
              f"{'OK' if ok_range else 'MISS'}  conf={food.get('confidence')}  [{source}, {times[-1]:.1f}s]")
    n = len(rows)
    print()
    print(f"Photos: {n}   model: {os.getenv('OPENAI_MODEL') or llm.provider()}")
    print(f"Named the right food:      {named}/{n} ({named / n:.0%})")
    print(f"True count inside range:   {in_range}/{n} ({in_range / n:.0%})")
    print(f"Count within 10%:          {close}/{n} ({close / n:.0%})")
    if errors:
        print(f"Average counting error:    {sum(errors) / len(errors):.0%} (when the food was named)")
    print(f"Average time per photo:    {sum(times) / n:.1f}s")
    if out:
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0]))
            w.writeheader()
            w.writerows(results)
        print(f"Per-photo results saved to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "eval_photos", sys.argv[2] if len(sys.argv) > 2 else None)
