"""Camera at the business: watches the leftover counter and donates what's left at closing time.

Two models, each doing what it's good at:
  - WATCH (all day, on this laptop): a fast object detector notices food and counts it, live.
    By default it's YOLO-World, which can be told by name what to look for ("popcorn bag", "cookies").
    If that can't load, it falls back to the standard detector, which only knows ten foods.
  - IDENTIFY (once, at closing time): the snapshot goes to the vision AI model on the Uplink server,
    which names the food, groups it by type and lists likely allergens. The detector's guess is only a hint.
    Without an AI key, the detector's counts are used directly.
Video never leaves this laptop; only the live counts and the one closing-time snapshot are sent.

Setup (one time):  pip3 install ultralytics opencv-python requests
Run (with the Uplink server running on port 5050):
    python3 camera.py --business campus-cafe
    python3 camera.py --business campus-cafe --detector coco      # standard detector only
    python3 camera.py --business campus-cafe --image test.jpg     # test with a photo
Trigger closing time: press C in the camera window, or click "Closing time (camera)" on the dashboard.
"""
import argparse
import collections
import statistics
import sys
import time

import requests

# Everything the camera knows how to donate. "servings" = per detected item; tune with real food.
# "min_conf" raises the bar for labels that are often false alarms (the standard model calls snack bags "cake").
FOOD = {
    # hot prepared
    "pizza":         {"servings": 4, "category": "hot prepared",  "needs_cold": False, "allergens": ["dairy", "gluten"]},
    "hot dog":       {"servings": 1, "category": "hot prepared",  "needs_cold": False, "allergens": ["gluten"]},
    "burrito":       {"servings": 1, "category": "hot prepared",  "needs_cold": False, "allergens": ["gluten", "dairy"]},
    "rice bowl":     {"servings": 1, "category": "hot prepared",  "needs_cold": False, "allergens": ["soy"]},
    "pasta tray":    {"servings": 6, "category": "hot prepared",  "needs_cold": False, "allergens": ["gluten", "dairy"]},
    "tray of food":  {"servings": 8, "category": "hot prepared",  "needs_cold": False, "allergens": []},
    # cold prepared
    "sandwich":      {"servings": 1, "category": "cold prepared", "needs_cold": True,  "allergens": ["gluten"]},
    "salad":         {"servings": 1, "category": "cold prepared", "needs_cold": True,  "allergens": []},
    "sushi":         {"servings": 1, "category": "cold prepared", "needs_cold": True,  "allergens": ["fish", "soy"]},
    "yogurt cup":    {"servings": 1, "category": "cold prepared", "needs_cold": True,  "allergens": ["dairy"]},
    "milk carton":   {"servings": 1, "category": "cold prepared", "needs_cold": True,  "allergens": ["dairy"]},
    # packaged / baked
    "donut":         {"servings": 1, "category": "packaged",      "needs_cold": False, "allergens": ["gluten", "dairy", "eggs"]},
    "cake":          {"servings": 8, "category": "packaged",      "needs_cold": False, "allergens": ["gluten", "dairy", "eggs"], "min_conf": 0.6},
    "muffin":        {"servings": 1, "category": "packaged",      "needs_cold": False, "allergens": ["gluten", "dairy", "eggs"]},
    "bagel":         {"servings": 1, "category": "packaged",      "needs_cold": False, "allergens": ["gluten"]},
    "bread loaf":    {"servings": 10, "category": "packaged",     "needs_cold": False, "allergens": ["gluten"]},
    "cookies":       {"servings": 2, "category": "packaged",      "needs_cold": False, "allergens": ["gluten", "dairy", "eggs"]},
    "popcorn bag":   {"servings": 4, "category": "packaged",      "needs_cold": False, "allergens": ["dairy"]},
    "chips bag":     {"servings": 2, "category": "packaged",      "needs_cold": False, "allergens": []},
    "granola bar":   {"servings": 1, "category": "packaged",      "needs_cold": False, "allergens": ["nuts", "gluten"]},
    # produce
    "apple":         {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
    "banana":        {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
    "orange":        {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
    "broccoli":      {"servings": 2, "category": "produce",       "needs_cold": False, "allergens": []},
    "carrot":        {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
}
# the standard detector (COCO) only knows these; YOLO-World is given every name in FOOD
COCO_FOODS = {"pizza", "hot dog", "sandwich", "donut", "cake", "apple", "banana", "orange", "broccoli", "carrot"}
SAFE_MINUTES = {"hot prepared": 120, "cold prepared": 90, "packaged": 1440, "produce": 720}
LBS_PER_SERVING = 0.4
SMOOTH_FRAMES = 15


def donations_from_counts(counts):
    """Turn stable detector counts into one donation per food category (used when no AI model is available)."""
    by_cat = collections.defaultdict(lambda: {"items": [], "servings": 0, "allergens": set(), "needs_cold": False})
    for name, n in counts.items():
        if n <= 0 or name not in FOOD:
            continue
        info = FOOD[name]
        g = by_cat[info["category"]]
        g["items"].append(f"{name} x{n}")
        g["servings"] += n * info["servings"]
        g["allergens"] |= set(info["allergens"])
        g["needs_cold"] |= info["needs_cold"]
    out = []
    for cat, g in by_cat.items():
        lbs = g["servings"] * LBS_PER_SERVING
        out.append({
            "items": g["items"], "servings": g["servings"], "weight_lbs": [round(lbs * 0.8, 1), round(lbs * 1.2, 1)],
            "allergens": sorted(g["allergens"]), "category": cat, "needs_cold": g["needs_cold"],
            # the detector can't read labels: say so, so the agents ask before ruling shelters in or out
            "allergens_unverified": True,
            "safe_minutes": SAFE_MINUTES[cat], "notes": "Counted by the camera's detector at closing time.",
        })
    return out


def stable_counts(history):
    """Median count per food over recent frames: ignores a hand or a person passing through."""
    names = {k for frame in history for k in frame}
    return {k: int(statistics.median(frame.get(k, 0) for frame in history)) for k in sorted(names)}


def hint_text(counts):
    return ", ".join(f"{k} x{v}" for k, v in counts.items() if v) or "nothing"


def load_detector(kind, model_path):
    """Returns (model, label). kind: 'auto' tries YOLO-World first, 'world' requires it, 'coco' is the standard model."""
    if kind in ("auto", "world"):
        try:
            from ultralytics import YOLOWorld
            model = YOLOWorld("yolov8s-worldv2.pt")
            model.set_classes(list(FOOD))      # tell it, by name, what food to look for
            return model, f"YOLO-World ({len(FOOD)} foods)"
        except Exception as e:  # noqa: BLE001 - fall back to the standard detector
            if kind == "world":
                sys.exit(f"Couldn't load YOLO-World: {e}")
            print(f"YOLO-World unavailable ({type(e).__name__}: {e}); using the standard detector (10 foods).")
    from ultralytics import YOLO
    return YOLO(model_path), "standard detector (10 foods)"


class Uplink:
    def __init__(self, server, business):
        self.server, self.business = server.rstrip("/"), business
        self.closing_seq = self._closing()["seq"]

    def _closing(self):
        try:
            return requests.get(f"{self.server}/api/closing", timeout=2).json()
        except requests.RequestException:
            return {"seq": 0, "business": None}

    def closing_time(self):
        """True once each time someone clicks "Closing time" on the dashboard (for us or for everyone)."""
        c = self._closing()
        if c["seq"] != self.closing_seq:
            self.closing_seq = c["seq"]
            return c.get("business") in (None, self.business)
        return False

    def status(self, counts):
        try:
            requests.post(f"{self.server}/api/camera/status", json={"business": self.business, "counts": counts}, timeout=2)
        except requests.RequestException:
            pass

    def identify(self, counts, jpeg_bytes):
        """Ask the vision AI model what's really there. Returns a list of donations, or None if no model answered."""
        if not jpeg_bytes:
            return None
        try:
            r = requests.post(f"{self.server}/api/vision", files={"photo": ("closing.jpg", jpeg_bytes, "image/jpeg")},
                              data={"multi": "1", "hint": hint_text(counts)}, timeout=90).json()
        except requests.RequestException:
            return None
        if r.get("source") in (None, "demo", "fallback"):
            return None
        return r.get("foods", [])

    def donate(self, counts, jpeg_bytes):
        print("Closing time. Detector saw:", hint_text(counts))
        foods = self.identify(counts, jpeg_bytes)
        if foods is not None:
            print(f"Vision model identified {len(foods)} donation(s)." if foods else "Vision model sees no food.")
        else:
            foods = donations_from_counts(counts)
            print("No AI model available; using the detector's counts (allergens marked unconfirmed).")
        if not foods:
            print("Nothing to donate.")
            return
        for f in foods:
            r = requests.post(f"{self.server}/api/donate", json={"food": f, "business": self.business}, timeout=5).json()
            print(f"  Donated {f['servings']} servings of {', '.join(f['items'])} ({f['category']}) as {r.get('id')}")


def detect(model, frame, conf):
    """Run the detector on one frame. Returns (counts, boxes) for food only, honoring per-food confidence bars."""
    result = model.predict(frame, conf=conf, verbose=False)[0]
    counts, boxes = collections.Counter(), []
    for box in result.boxes:
        name = result.names[int(box.cls)]
        score = float(box.conf)
        if name not in FOOD or score < FOOD[name].get("min_conf", conf):
            continue
        counts[name] += 1
        boxes.append((name, score, tuple(map(int, box.xyxy[0]))))
    return counts, boxes


def main():
    ap = argparse.ArgumentParser(description="Uplink camera at the business")
    ap.add_argument("--server", default="http://localhost:5050")
    ap.add_argument("--business", default="campus-cafe", help="business id from data/businesses.json")
    ap.add_argument("--camera", type=int, default=0, help="webcam index (0 = built-in)")
    ap.add_argument("--image", help="use a photo instead of a webcam (for testing)")
    ap.add_argument("--detector", choices=["auto", "world", "coco"], default="auto",
                    help="auto = YOLO-World if it loads, else the standard detector")
    ap.add_argument("--model", default="yolov8n.pt", help="standard detector weights")
    ap.add_argument("--conf", type=float, default=0.3, help="detection confidence threshold")
    ap.add_argument("--no-window", action="store_true", help="don't open a preview window")
    args = ap.parse_args()

    try:
        import cv2
    except ImportError:
        sys.exit("Missing packages. Run:  pip3 install ultralytics opencv-python requests")

    model, label = load_detector(args.detector, args.model)
    up = Uplink(args.server, args.business)
    still = cv2.imread(args.image) if args.image else None
    if args.image and still is None:
        sys.exit(f"Couldn't read {args.image}")
    cap = None if args.image else cv2.VideoCapture(args.camera)
    if cap is not None and not cap.isOpened():
        sys.exit("Couldn't open the webcam. On a Mac, allow Terminal in System Settings > Privacy & Security > Camera, "
                 "then quit Terminal (Cmd+Q) and reopen it.")

    history = collections.deque(maxlen=SMOOTH_FRAMES)
    last_status = 0.0
    print(f"Watching for food at '{args.business}' with the {label}. Press C (or click Closing time) to donate; Q quits.")
    while True:
        frame = still.copy() if still is not None else cap.read()[1]
        if frame is None:
            time.sleep(0.1)
            continue
        counts, boxes = detect(model, frame, args.conf)
        history.append(dict(counts))
        stable = stable_counts(history)

        if time.time() - last_status > 1:
            up.status(stable)
            last_status = time.time()

        key = -1
        if not args.no_window:
            shown = frame.copy()
            for name, score, (x1, y1, x2, y2) in boxes:
                cv2.rectangle(shown, (x1, y1), (x2, y2), (40, 160, 80), 2)
                cv2.putText(shown, f"{name} {score:.0%}", (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (40, 160, 80), 2)
            cv2.putText(shown, f"Sees: {hint_text(stable)}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(shown, f"{label}  [C] closing time  [Q] quit", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            cv2.imshow("Uplink camera", shown)
            key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("c") or up.closing_time():
            ok, jpg = cv2.imencode(".jpg", frame)   # the clean frame, without our boxes drawn on it
            up.donate(stable, jpg.tobytes() if ok else None)
        if still is not None:
            time.sleep(0.5)

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
