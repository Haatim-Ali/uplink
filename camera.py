"""Camera at the business: watches the leftover counter and donates what's left at closing time.

Owner: (teammate) -- this is a working starter; tune the numbers below with real food in front of a webcam.

Setup (one time, takes a few minutes; the model file downloads on first run):
    pip3 install ultralytics opencv-python requests

Run (with the Uplink server already running on port 5050):
    python3 camera.py --business campus-cafe
    python3 camera.py --business campus-cafe --image test.jpg     # test with a photo instead of a webcam

How it triggers a donation:
    - press C in the camera window, or
    - click "Closing time (camera)" on the dashboard.

What it does:
    1. Runs a ready-made object detector (YOLO) on every frame. It already knows pizza, sandwich,
       hot dog, donut, cake, apple, banana, orange, broccoli and carrot. No training needed.
    2. Smooths the counts over the last ~15 frames so a hand passing by doesn't count.
    3. Sends what it sees to the dashboard every second ("Camera at Bowers Ave Cafe sees: 3 pizza").
    4. At closing time, takes a snapshot. If the server has an AI key, the vision model describes the
       food in detail; otherwise it builds the donation from the detector's counts. Different kinds of
       food (hot, cold, produce, baked) become separate donations, since the safety rules differ.
       Video never leaves this laptop; only the counts and the one snapshot go to the Uplink server.
"""
import argparse
import collections
import statistics
import sys
import time

import requests

# What each detected thing means for a donation. Tune "servings" with real food in front of the camera.
FOOD = {
    "pizza":    {"servings": 4, "category": "hot prepared",  "needs_cold": False, "allergens": ["dairy", "gluten"]},
    "hot dog":  {"servings": 1, "category": "hot prepared",  "needs_cold": False, "allergens": ["gluten"]},
    "sandwich": {"servings": 1, "category": "cold prepared", "needs_cold": True,  "allergens": ["gluten"]},
    "donut":    {"servings": 1, "category": "packaged",      "needs_cold": False, "allergens": ["gluten", "dairy", "eggs"]},
    "cake":     {"servings": 8, "category": "packaged",      "needs_cold": False, "allergens": ["gluten", "dairy", "eggs"]},
    "apple":    {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
    "banana":   {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
    "orange":   {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
    "broccoli": {"servings": 2, "category": "produce",       "needs_cold": False, "allergens": []},
    "carrot":   {"servings": 1, "category": "produce",       "needs_cold": False, "allergens": []},
}
SAFE_MINUTES = {"hot prepared": 120, "cold prepared": 90, "packaged": 1440, "produce": 720}
LBS_PER_SERVING = 0.4
SMOOTH_FRAMES = 15


def donations_from_counts(counts):
    """Turn stable detector counts into one donation per food category."""
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
            "safe_minutes": SAFE_MINUTES[cat], "notes": "Spotted by the camera at closing time.",
        })
    return out


def stable_counts(history):
    """Median count per food over recent frames: ignores a hand or a person passing through."""
    names = {k for frame in history for k in frame}
    return {k: int(statistics.median(frame.get(k, 0) for frame in history)) for k in sorted(names)}


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

    def donate(self, counts, jpeg_bytes):
        foods = donations_from_counts(counts)
        if not foods:
            print("Closing time, but the camera sees no food. Nothing to donate.")
            return
        # If the server has an AI key, let the vision model describe a single-kind spread in detail.
        if jpeg_bytes and len(foods) == 1:
            try:
                r = requests.post(f"{self.server}/api/vision", files={"photo": ("closing.jpg", jpeg_bytes, "image/jpeg")}, timeout=60).json()
                if r.get("source") not in ("demo", "fallback"):
                    foods = [dict(r["food"], notes="Described by the vision model from the closing-time snapshot.")]
            except requests.RequestException:
                pass
        for f in foods:
            r = requests.post(f"{self.server}/api/donate", json={"food": f, "business": self.business}, timeout=5).json()
            print(f"Donated {f['servings']} servings of {', '.join(f['items'])} ({f['category']}) as {r.get('id')}")


def main():
    ap = argparse.ArgumentParser(description="Uplink camera at the business")
    ap.add_argument("--server", default="http://localhost:5050")
    ap.add_argument("--business", default="campus-cafe", help="business id from data/businesses.json")
    ap.add_argument("--camera", type=int, default=0, help="webcam index (0 = built-in)")
    ap.add_argument("--image", help="use a photo instead of a webcam (for testing)")
    ap.add_argument("--model", default="yolov8n.pt", help="detector weights; downloads on first run")
    ap.add_argument("--conf", type=float, default=0.35, help="detection confidence threshold")
    ap.add_argument("--no-window", action="store_true", help="don't open a preview window")
    args = ap.parse_args()

    try:
        import cv2
        from ultralytics import YOLO
    except ImportError:
        sys.exit("Missing packages. Run:  pip3 install ultralytics opencv-python requests")

    model = YOLO(args.model)
    up = Uplink(args.server, args.business)
    still = cv2.imread(args.image) if args.image else None
    if args.image and still is None:
        sys.exit(f"Couldn't read {args.image}")
    cap = None if args.image else cv2.VideoCapture(args.camera)
    if cap is not None and not cap.isOpened():
        sys.exit("Couldn't open the webcam. On a Mac, allow Terminal to use the camera in System Settings > Privacy.")

    history = collections.deque(maxlen=SMOOTH_FRAMES)
    last_status = 0.0
    print(f"Watching for food at '{args.business}'. Press C in the window (or click Closing time on the dashboard). Q quits.")
    while True:
        frame = still.copy() if still is not None else cap.read()[1]
        if frame is None:
            time.sleep(0.1)
            continue
        result = model.predict(frame, conf=args.conf, verbose=False)[0]
        counts = collections.Counter()
        for box in result.boxes:
            name = result.names[int(box.cls)]
            if name in FOOD:
                counts[name] += 1
                if not args.no_window:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (40, 160, 80), 2)
                    cv2.putText(frame, name, (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 160, 80), 2)
        history.append(dict(counts))
        stable = stable_counts(history)

        if time.time() - last_status > 1:
            up.status(stable)
            last_status = time.time()

        key = -1
        if not args.no_window:
            label = ", ".join(f"{v} {k}" for k, v in stable.items() if v) or "no food"
            cv2.putText(frame, f"Sees: {label}   [C] closing time  [Q] quit", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imshow("Uplink camera", frame)
            key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("c") or up.closing_time():
            ok, jpg = cv2.imencode(".jpg", frame)
            up.donate(stable, jpg.tobytes() if ok else None)
        if still is not None:
            time.sleep(0.5)

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
