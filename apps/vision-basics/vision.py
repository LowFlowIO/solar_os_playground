"""A step-by-step introduction to solaros.vision.

Read main() first: it contains the complete image-processing pipeline.
The two small helpers below handle file selection and display/input only.
"""

import sys

import solaros
from solaros import gfx


def input_path():
    # Playground passes arguments unchanged. Assets live beside this script,
    # rather than in the shell's current working directory.
    directory = sys.argv[0].rsplit("/", 1)[0] if "/" in sys.argv[0] else "."
    if len(sys.argv) == 1:
        return directory + "/dog.jpg"
    if len(sys.argv) == 3 and sys.argv[1] == "--file":
        return sys.argv[2]
    raise ValueError("Usage: playground run vision-basics [--file PATH]")


def show(picture, title, note, blobs=None, mask_size=None):
    """Show a stage; return False on exit, True on Space/Enter/Right."""
    image = solaros.image
    screen_w, screen_h = gfx.size()
    source_w, source_h = image.size(picture)
    scale = min((screen_w - 8) / source_w, (screen_h - 64) / source_h)
    draw_w, draw_h = max(1, int(source_w * scale)), max(1, int(source_h * scale))
    left, top = (screen_w - draw_w) // 2, 34 + (screen_h - 64 - draw_h) // 2

    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_MONO_12)
    # Text positions use baselines. Keep labels inside even a small display.
    columns = max(1, (screen_w - 8) // 8)
    gfx.text(4, 14, title[:columns])
    gfx.text(4, 28, note[:columns])
    image.draw(picture, left, top, draw_w, draw_h)

    if blobs is not None:
        # Detection used the resized mask. Map its coordinates to this view
        # of the original image; these are NOT display-pixel coordinates.
        mask_w, mask_h = mask_size
        for blob in blobs:
            x = left + blob["x"] * draw_w // mask_w
            y = top + blob["y"] * draw_h // mask_h
            right = left + (blob["x"] + blob["width"]) * draw_w // mask_w
            bottom = top + (blob["y"] + blob["height"]) * draw_h // mask_h
            # A one-pixel margin keeps a black box visible around dark shapes.
            gfx.rect(x - 1, y - 1, max(1, right - x) + 2, max(1, bottom - y) + 2)
            cx = left + int(blob["cx"] * draw_w / mask_w)
            cy = top + int(blob["cy"] * draw_h / mask_h)
            gfx.color(gfx.WHITE)
            gfx.fill_rect(cx - 2, cy - 2, 5, 5)
            gfx.color(gfx.BLACK)
            gfx.line(cx - 2, cy, cx + 2, cy)
            gfx.line(cx, cy - 2, cx, cy + 2)

    gfx.text(4, screen_h - 5, "Space > Q exit"[:columns])
    gfx.present()
    # Redraw only when advancing. A bounded wait keeps exit responsive.
    while not solaros.should_exit():
        key = gfx.getch(250)
        if key in (gfx.KEY_ESCAPE, ord("q"), ord("Q")):
            return False
        if key in (ord(" "), 10, 13, gfx.KEY_RIGHT):
            return True
    return False


def main():
    image = getattr(solaros, "image", None)
    vision = getattr(solaros, "vision", None)
    if image is None or vision is None or not hasattr(vision, "opening"):
        print("Vision Basics needs media.image and service.imlib (vision group).")
        print("Use SolarOS 4.16.0+ with Python and PSRAM; full includes them.")
        return

    # Transformations return NEW native image handles. Keep them for viewing
    # and close every one in finally, including on early exit or failure.
    pictures = []
    gfx.begin()
    try:
        width, height = gfx.size()
        if width < 128 or height < 96:
            raise ValueError("Vision Basics needs a display of at least 128x96")

        # 1. Decode a stored PNG/JPEG/GIF/WebP into native PSRAM, not a Python
        # pixel array. The bundled dog photograph also has textured grass,
        # so later steps show how thresholding treats foreground/background.
        original = image.open(input_path())
        pictures.append(original)
        if not show(original, "1/5 Source", "image.open"):
            return

        # 2. Grayscale Gaussian blur reduces noise before segmentation.
        # ksize is a RADIUS: 1 means a 3x3 kernel. Bound processing to 320x240
        # and preserve aspect ratio. Large inputs need this explicit resize.
        source_w, source_h = image.size(original)
        scale = min(1.0, 320 / source_w, 240 / source_h)
        smooth = vision.gaussian(original, {
            "ksize": 1,
            "output_width": max(1, int(source_w * scale)),
            "output_height": max(1, int(source_h * scale)),
        })
        pictures.append(smooth)
        if not show(smooth, "2/5 Blur", "vision.gaussian"):
            return

        # 3. Match dark pixels, with inclusive grayscale limits in 0..255.
        # binary() turns MATCHES WHITE (255) and everything else black (0).
        # Change 100 to experiment, or tune it for your own input image.
        mask = vision.binary(smooth, {"thresholds": [[0, 140]]})
        pictures.append(mask)
        if not show(mask, "3/5 Mask", "vision.binary"):
            return

        # 4. Opening erodes then dilates the WHITE foreground. Applied to a
        # binary mask, it removes small specks and can break thin connections.
        clean = vision.opening(mask, {"ksize": 2})
        pictures.append(clean)
        if not show(clean, "4/5 Clean", "vision.opening"):
            return

        # 5. Find connected WHITE regions in the cleaned mask. A result is a
        # dictionary, not an image. Pixel/area thresholds reject tiny regions;
        # these numbers refer to the processed mask, not the displayed size.
        result = vision.blobs(clean, {
            "thresholds": [[255, 255]],
            "pixels_threshold": 50,
            "area_threshold": 100,
            "max_blobs": 1,
        })
        print("Regions:", len(result["blobs"]), "Truncated:", result["truncated"])
        for blob in result["blobs"]:
            print("Box:", blob["x"], blob["y"], blob["width"], blob["height"],
                  "Center:", blob["cx"], blob["cy"], "Pixels:", blob["pixels"])
        note = "%d regions%s" % (len(result["blobs"]), "+" if result["truncated"] else "")
        show(original, "5/5 Regions", note, result["blobs"], image.size(clean))
    finally:
        try:
            while pictures:
                image.close(pictures.pop())
        finally:
            gfx.end()


if __name__ == "__main__":
    main()
