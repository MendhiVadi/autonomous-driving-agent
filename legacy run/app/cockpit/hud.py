"""Cockpit layout and HUD drawing that needs no simulator.

Everything here takes plain pygame objects so the panels can be rendered and
checked offline. The simulator session supplies the live values.
"""
import math

from cockpit.graphics import format_speed_kmh
from vehicle.transmission import manual_gear_name, recommended_shift, selector_name

STALE_FEED_AFTER_S = 2.5


def compute_layout(width, height, camera_profile):
    """Return the six cockpit zones as (x, y, w, h) tuples."""
    top_h = int(height * 0.24)
    side_w = int(width * 0.16)
    instrument_w = int(width * 0.19)
    layout = {
        "map": (0, 0, side_w, top_h),
        "rear": (side_w, 0, width - side_w - instrument_w, top_h),
        "instrument": (width - instrument_w, 0, instrument_w, top_h),
        "left": (0, top_h, side_w, height - top_h),
        "right": (width - side_w, top_h, side_w, height - top_h),
        "front": (side_w, top_h, width - 2 * side_w, height - top_h),
    }
    if camera_profile == "map":
        layout["front"] = (0, top_h, width, height - top_h)
    return layout


def fit_text(font, text, max_width):
    """Shorten text with '...' until it fits, so labels never run off a panel."""
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "...")[0] > max_width:
        text = text[:-1]
    return (text + "...") if text else ""


def wrap_text(font, text, max_width, max_lines=2):
    """Word-wrap into at most ``max_lines`` lines; only the last line is ever shortened."""
    lines, current = [], ""
    for word in str(text).split():
        trial = (current + " " + word).strip()
        if current and font.size(trial)[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return [fit_text(font, line, max_width) for line in lines]


def draw_text_fitted(surface, font, text, color, rect, align="left"):
    """Draw one line clipped inside ``rect`` using an ellipsis when needed."""
    x, y, width, height = rect
    rendered = font.render(fit_text(font, text, width), True, color)
    if align == "center":
        position = rendered.get_rect(center=(x + width // 2, y + height // 2))
    elif align == "right":
        position = rendered.get_rect(midright=(x + width, y + height // 2))
    else:
        position = rendered.get_rect(midleft=(x, y + height // 2))
    surface.blit(rendered, position)


def draw_status_panel(pygame, display, fonts, rect, title, status, hints):
    """Fill the upper-centre zone with live status instead of a static label.

    A long status wraps onto a second line (smaller type if needed) rather than
    being cut off, so messages like "OFF ROUTE - RE-ALIGNING IN 3 S" stay readable.
    """
    x, y, width, height = rect
    pygame.draw.rect(display, (8, 12, 17), rect)
    pygame.draw.rect(display, (55, 68, 82), rect, 2)
    text_width = width - 24
    draw_text_fitted(display, fonts["small"], title, (142, 158, 176), (x + 12, y + 8, text_width, 20))
    status = status or "READY"
    font = fonts["hud"]
    lines = wrap_text(font, status, text_width, max_lines=2)
    if len(lines) > 1 and font.size(" ".join(lines))[0] > 2 * text_width:
        font = fonts["small"]
        lines = wrap_text(font, status, text_width, max_lines=2)
    line_height = font.get_linesize()
    for index, line in enumerate(lines):
        rendered = font.render(line, True, (240, 244, 248))
        display.blit(rendered, (x + 12, y + 30 + index * line_height))
    hint_top = max(y + 70, y + 30 + len(lines) * line_height + 6)
    for index, hint in enumerate(hints):
        draw_text_fitted(display, fonts["small"], hint, (150, 168, 188),
                         (x + 12, hint_top + index * 19, text_width, 19))


def draw_feed_overlay(pygame, display, fonts, rect, caption, age_s):
    """Name a camera feed and flag it plainly when frames stop arriving."""
    x, y, width, height = rect
    label = caption
    color = (190, 205, 220)
    if age_s is None:
        label, color = caption + "  WAITING", (255, 196, 76)
    elif age_s > STALE_FEED_AFTER_S:
        label, color = f"{caption} - NO FRAME {age_s:.0f}s", (255, 112, 96)
    text = fit_text(fonts["small"], label, width - 16)
    rendered = fonts["small"].render(text, True, color)
    badge = pygame.Surface((rendered.get_width() + 10, rendered.get_height() + 4), pygame.SRCALPHA)
    badge.fill((0, 0, 0, 170))
    badge.blit(rendered, (5, 2))
    display.blit(badge, (x + 6, y + 6))


def draw_focus_hint(pygame, display, fonts, front_rect, message):
    """Small pill at the foot of the windshield; never over the road ahead."""
    x, y, width, height = front_rect
    text = fit_text(fonts["small"], message, width - 40)
    rendered = fonts["small"].render(text, True, (255, 214, 92))
    pill = pygame.Surface((rendered.get_width() + 24, rendered.get_height() + 10), pygame.SRCALPHA)
    pill.fill((0, 0, 0, 190))
    pill.blit(rendered, (12, 5))
    display.blit(pill, pill.get_rect(midbottom=(x + width // 2, y + height - 14)))


def draw_status_line(pygame, display, fonts, front_rect, message):
    """Top-centre status strip over the windshield with a legible backing."""
    if not message:
        return
    x, y, width, height = front_rect
    text = fit_text(fonts["small"], message, width - 40)
    rendered = fonts["small"].render(text, True, (255, 214, 92))
    strip = pygame.Surface((rendered.get_width() + 24, rendered.get_height() + 10), pygame.SRCALPHA)
    strip.fill((0, 0, 0, 170))
    strip.blit(rendered, (12, 5))
    display.blit(strip, strip.get_rect(midtop=(x + width // 2, y + 10)))


def draw_instruments(pygame, display, fonts, rect, transmission_config, speed, rpm,
                     actual_gear, requested_gear, clutch_value, parked_state,
                     parking_brake, control, automatic, gear_in_sync):
    """Speedometer, tachometer, selector, gear and pedal bars without overlaps.

    ``automatic`` is true when CARLA's stock gearbox is shifting: the selector
    then reports the real gear and no manual shift advice is shown.
    """
    x, y, width, height = rect
    hud_font, small_font, tick_font = fonts["hud"], fonts["small"], fonts["tick"]
    pygame.draw.rect(display, (7, 10, 15), rect)
    pygame.draw.rect(display, (82, 98, 119), rect, 3)
    radius = max(18, min(34, (height - 66) // 2, (width // 2 - 14) // 2))
    center_y = y + 8 + radius
    centers = ((x + width // 4, center_y), (x + width * 3 // 4, center_y))
    tach_scale_rpm = 7000.0
    redline = transmission_config.redline_rpm
    tach_color = ((255, 82, 72) if rpm >= redline * 0.91 else
                  (255, 186, 64) if rpm >= redline * 0.77 else (235, 240, 245))
    values = (
        (min(speed, 180.0) / 180.0, (70, 205, 255), format_speed_kmh(speed), "km/h", False),
        (min(rpm, tach_scale_rpm) / tach_scale_rpm, tach_color, None, "x1000 rpm", True),
    )
    redline_fraction = redline / tach_scale_rpm
    for center, (fraction, color, value, unit, is_tach) in zip(centers, values):
        pygame.draw.circle(display, (12, 18, 27), center, radius)
        pygame.draw.circle(display, (90, 105, 123), center, radius, 2)
        if is_tach:
            arc_radius = radius - 5
            for segment in range(12):
                start_fraction = redline_fraction + (1.0 - redline_fraction) * segment / 12.0
                end_fraction = redline_fraction + (1.0 - redline_fraction) * (segment + 1) / 12.0
                start_angle = math.radians(135 + start_fraction * 270)
                end_angle = math.radians(135 + end_fraction * 270)
                pygame.draw.line(
                    display, (230, 55, 48),
                    (center[0] + int(arc_radius * math.cos(start_angle)),
                     center[1] + int(arc_radius * math.sin(start_angle))),
                    (center[0] + int(arc_radius * math.cos(end_angle)),
                     center[1] + int(arc_radius * math.sin(end_angle))), 3)
        tick_count = 14 if is_tach else 10
        for tick in range(tick_count + 1):
            tick_fraction = tick / tick_count
            angle = math.radians(135 + tick_fraction * 270)
            outer = (center[0] + int((radius - 3) * math.cos(angle)),
                     center[1] + int((radius - 3) * math.sin(angle)))
            major = tick % 2 == 0
            inner_length = radius - (10 if major else 6)
            inner = (center[0] + int(inner_length * math.cos(angle)),
                     center[1] + int(inner_length * math.sin(angle)))
            tick_color = ((255, 72, 62) if is_tach and tick_fraction >= redline_fraction
                          else (154, 168, 184))
            pygame.draw.line(display, tick_color, inner, outer, 2 if major else 1)
            if is_tach and tick % 4 == 0:
                label = tick_font.render(str(tick // 2), True, tick_color)
                label_radius = radius - 14
                display.blit(label, label.get_rect(center=(
                    center[0] + int(label_radius * math.cos(angle)),
                    center[1] + int(label_radius * math.sin(angle)))))
        angle = math.radians(135 + max(0.0, min(1.0, fraction)) * 270)
        end = (center[0] + int((radius - 11) * math.cos(angle)),
               center[1] + int((radius - 11) * math.sin(angle)))
        pygame.draw.line(display, (245, 247, 250) if is_tach else color, center, end, 3)
        pygame.draw.circle(display, (224, 62, 54) if is_tach else color, center, 4)
        if value is not None:
            surface = hud_font.render(value, True, (245, 248, 252))
            display.blit(surface, surface.get_rect(center=(center[0], center[1] + 2)))
        unit_surface = tick_font.render(unit, True, color)
        display.blit(unit_surface, unit_surface.get_rect(center=(center[0], center[1] + radius - 11)))

    row_y = y + height - 50
    selected = selector_name(requested_gear if not automatic else
                             (-1 if requested_gear < 0 else 0 if requested_gear == 0 else 1),
                             parked_state)
    for index, label in enumerate("PRND"):
        color = (70, 205, 255) if label == selected else (112, 125, 142)
        surface = small_font.render(label, True, color)
        display.blit(surface, (x + 10 + index * 22, row_y))
    if automatic:
        gear_text = ("P" if parked_state else "R" if requested_gear < 0 else
                     "N" if requested_gear == 0 else f"D{max(1, int(actual_gear))}")
    else:
        gear_text = manual_gear_name(requested_gear, parked_state)
    gear_box = pygame.Rect(x + width - 58, row_y - 3, 48, 21)
    pygame.draw.rect(display, (20, 33, 45), gear_box, border_radius=5)
    pygame.draw.rect(display, (70, 205, 255), gear_box, 1, border_radius=5)
    gear_surface = small_font.render(gear_text, True, (92, 220, 255))
    display.blit(gear_surface, gear_surface.get_rect(center=gear_box.center))

    hint = ""
    hint_color = tach_color
    if not automatic:
        if not gear_in_sync:
            hint, hint_color = "GEAR SYNC", (255, 102, 92)
        else:
            hint = recommended_shift(actual_gear, rpm, control.throttle,
                                     transmission_config, speed)
    if parking_brake:
        hint, hint_color = "PARK BRAKE", (255, 116, 96)
    if hint:
        surface = tick_font.render(hint, True, hint_color)
        display.blit(surface, surface.get_rect(midtop=(x + width // 2, row_y + 22)))

    bars = (("G", control.throttle, (77, 214, 144)),
            ("B", control.brake, (255, 102, 92)),
            ("C", clutch_value, (255, 196, 76)))
    bar_y = y + height - 17
    column = width // 3
    for index, (label, value, color) in enumerate(bars):
        bar_x = x + 8 + index * column
        display.blit(tick_font.render(label, True, (210, 220, 230)), (bar_x, bar_y))
        track = pygame.Rect(bar_x + 12, bar_y + 3, max(14, column - 26), 7)
        pygame.draw.rect(display, (48, 57, 70), track)
        pygame.draw.rect(display, color, (track.x, track.y,
                                          int(track.width * max(0.0, min(1.0, value))), track.height))
