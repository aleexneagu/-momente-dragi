#!/usr/bin/env python3
"""
Polaroid -> broderie: prototip Etapa 0.

Pipeline: crop polaroid -> enhance -> cuantizare culori (Lab k-means)
-> mapare pe paleta de fire Brother (PEC, 64 culori) -> umplere tatami
cu unghi auto per culoare + underlay + contur -> export .pes/.dst
+ preview realist PNG + lista de fire.

Unitati: intern lucram in pixeli de 0.2 mm; fisierul de broderie e in 0.1 mm.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
import pyembroidery
from pyembroidery import EmbThread

MM_PER_PX = 0.1          # rezolutia de lucru
PX = lambda mm: mm / MM_PER_PX


# ---------------------------------------------------------------- crop
def _crop_once(img: np.ndarray):
    """O trecere: daca marginile imaginii sunt o rama uniforma (orice culoare),
    intoarce dreptunghiul (x0, y0, x1, y1) al continutului, altfel None."""
    h, w = img.shape[:2]
    corners = np.concatenate([
        img[:h // 20, :w // 20].reshape(-1, 3),
        img[:h // 20, -w // 20:].reshape(-1, 3),
        img[-h // 20:, :w // 20].reshape(-1, 3),
        img[-h // 20:, -w // 20:].reshape(-1, 3),
    ]).astype(np.int16)
    border = np.median(corners, axis=0)
    if np.abs(corners - border).mean() > 28:
        return None                       # colturile nu sunt rama uniforma
    diff = np.abs(img.astype(np.int16) - border).sum(axis=2)
    mask = (diff > 60).astype(np.uint8)
    k = max(3, int(min(h, w) * 0.01) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return None
    i = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    x, y, cw, ch = stats[i, :4]
    if cw < 0.35 * w or ch < 0.35 * h:
        return None
    m = int(min(cw, ch) * 0.02)          # taie inauntru, fara halou de rama
    return (x + m, y + m, x + cw - m, y + ch - m)


def detect_crop_rect(img: np.ndarray):
    """Dreptunghiul fotografiei din rama polaroid (orice culoare de rama),
    in coordonatele imaginii originale. Treceri succesive: fundal, carton."""
    x0 = y0 = 0
    cur = img
    rect = (0, 0, img.shape[1], img.shape[0])
    for it in range(3):
        r = _crop_once(cur)
        if r is None:
            if it == 0:   # fallback: proportii tipice de polaroid
                h, w = img.shape[:2]
                mx = int(w * 0.08)
                ty = int(h * 0.07)
                return (mx, ty, w - mx, min(h, ty + w - 2 * mx))
            break
        rect = (x0 + r[0], y0 + r[1], x0 + r[2], y0 + r[3])
        stop = (r[2] - r[0]) > 0.9 * cur.shape[1] \
            and (r[3] - r[1]) > 0.9 * cur.shape[0]
        x0, y0 = rect[0], rect[1]
        cur = img[rect[1]:rect[3], rect[0]:rect[2]]
        if stop:                          # decupajul nu mai schimba mare lucru
            break
    return rect


def crop_polaroid(img: np.ndarray) -> np.ndarray:
    x0, y0, x1, y1 = detect_crop_rect(img)
    return img[y0:y1, x0:x1]


def detect_card_rect(img: np.ndarray, photo=None):
    """Polaroidul intreg (cu rama lui): fotografia detectata, extinsa cu
    proportiile reale de carton (poza 79, margini 4.5, banda jos 22 mm)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = photo or detect_crop_rect(img)
    pw, ph = x1 - x0, y1 - y0
    return (max(0, int(x0 - pw * 4.5 / 79)), max(0, int(y0 - ph * 6 / 79)),
            min(w, int(x1 + pw * 4.5 / 79)), min(h, int(y1 + ph * 22 / 79)))


def photo_in_selection(photo, sx, sy, sw, sh):
    """Fotografia detectata, in coordonatele selectiei — doar daca selectia
    arata ca un polaroid cu margini in jurul ei; altfel None."""
    px, py, pw, ph = photo
    x0, y0 = px - sx, py - sy
    ix0, iy0 = max(0, x0), max(0, y0)
    ix1, iy1 = min(sw, x0 + pw), min(sh, y0 + ph)
    if ix1 <= ix0 or iy1 <= iy0:
        return None
    inter = (ix1 - ix0) * (iy1 - iy0)
    if inter < 0.85 * pw * ph:            # fotografia nu e (toata) in selectie
        return None
    if not 0.30 * sw * sh < inter < 0.92 * sw * sh:
        return None                       # selectia e deja poza / e alta zona
    return (int(ix0), int(iy0), int(ix1), int(iy1))


def strip_border(img: np.ndarray) -> np.ndarray:
    """Daca selectia e un polaroid intreg, pastram doar fotografia din el:
    rama reala (carton deschis, uniform) ar iesi cusuta dublu cu rama noastra."""
    for _ in range(2):
        h, w = img.shape[:2]
        r = _crop_once(img)
        if r is None:
            break
        cw, ch = r[2] - r[0], r[3] - r[1]
        # fotografia ocupa o parte mare, dar nu toata selectia
        if not (0.55 * w < cw < 0.97 * w and 0.55 * h < ch < 0.97 * h):
            break
        border = np.ones((h, w), bool)
        border[r[1]:r[3], r[0]:r[2]] = False
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        if np.median(lab[..., 0][border]) < 140:   # rama nu e carton deschis
            break
        img = img[r[1]:r[3], r[0]:r[2]]
    return img


def text_paths(text: str, height_px: float, max_w_px: float):
    """Text 'scris de mana' -> trasee de running stitch (conturul literelor,
    dus-intors pentru o linie mai pronuntata)."""
    font_file = next((p for p in (
        "/mnt/c/Windows/Fonts/Inkfree.ttf",
        "/mnt/c/Windows/Fonts/segoesc.ttf",
        os.path.join(os.path.dirname(__file__), "fonts", "Caveat.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if os.path.exists(p)),
        None)

    def make(px):
        f = ImageFont.truetype(font_file, px) if font_file \
            else ImageFont.load_default(px)
        return f, f.getbbox(text)

    px = max(12, int(height_px * 1.35))
    font, bb = make(px)
    if bb[2] - bb[0] > max_w_px:          # textul nu incape: micsoram
        px = max(12, int(px * max_w_px / (bb[2] - bb[0])))
        font, bb = make(px)
    w, h = bb[2] - bb[0] + 6, bb[3] - bb[1] + 6
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((3 - bb[0], 3 - bb[1]), text, 255, font=font)
    mask = (np.array(im) > 128).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    paths = []
    for c in contours:
        c = c.reshape(-1, 2).astype(np.float32)
        p = resample(np.vstack([c, c[:1]]), 1.0)
        if p is not None:
            paths.append(np.vstack([p, p[::-1]]))
        else:                             # punctul de pe i: cateva impunsaturi
            cx, cy = c.mean(axis=0)
            d = PX(0.4)
            paths.append(np.array([(cx - d, cy), (cx + d, cy),
                                   (cx - d, cy), (cx + d, cy)], np.float32))
    return paths, (w, h)


def enhance(img: np.ndarray, sat: float = 1.25, clarity: float = 1.0) -> np.ndarray:
    """Pregatire adaptiva: fiecare poza e analizata si corectata dupa nevoie
    (balans de alb, luminozitate, granulatie, contrast local)."""
    arr = img.astype(np.float32)
    # balans de alb gray-world, temperat ca sa nu stearga tonul de polaroid
    means = arr.reshape(-1, 3).mean(axis=0)
    gains = np.clip(means.mean() / (means + 1e-6), 0.85, 1.18)
    arr = np.clip(arr * gains, 0, 255).astype(np.uint8)
    # corectie de vinieta: intunecarea radiala spre colturi (frecventa la
    # polaroide) taie gradiente in inele concentrice la cuantizare/sketch
    L0 = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    h0, w0 = L0.shape
    B = cv2.GaussianBlur(L0, (0, 0), min(h0, w0) / 5.0)
    yy, xx = np.mgrid[0:h0, 0:w0]
    rr = np.hypot((xx - w0 / 2) / w0, (yy - h0 / 2) / h0)
    corr = float(np.corrcoef(rr.ravel()[::7], B.ravel()[::7])[0, 1])
    if corr < -0.6:                      # camp clar radial: aplatizam
        gain = np.clip(float(np.median(B)) / np.maximum(B, 1e-3), 0.75, 1.7)
        arr = np.clip(arr.astype(np.float32) * gain[..., None],
                      0, 255).astype(np.uint8)
    # gamma automat: pozele intunecate se lumineaza, cele arse se tempereaza
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
    med = float(np.median(lab[..., 0])) / 255.0
    gamma = float(np.clip(math.log(0.45) / math.log(max(med, 0.05)), 0.65, 1.5))
    if abs(gamma - 1) > 0.05:
        lut = (np.power(np.linspace(0, 1, 256), gamma) * 255).astype(np.uint8)
        lab[..., 0] = lut[lab[..., 0]]
        arr = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    # netezire care pastreaza muchiile: granulatia de polaroid dispare
    arr = cv2.bilateralFilter(arr, 7, 45, 5)
    pil = Image.fromarray(arr)
    pil = ImageOps.autocontrast(pil, cutoff=2)
    pil = ImageEnhance.Color(pil).enhance(sat)
    pil = ImageEnhance.Contrast(pil).enhance(1.1)
    arr = np.array(pil)
    # contrast local adaptiv: cu cat poza e mai plata, cu atat mai mult CLAHE
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
    L = lab[..., 0]
    lap = cv2.Laplacian(L, cv2.CV_32F)
    detail = float(lap.std())
    clip = float(np.clip(2.0 * clarity * np.clip(18.0 / max(detail, 6.0), 0.7, 2.2),
                         1.0, 8.0))
    Lc = cv2.createCLAHE(clipLimit=clip, tileGridSize=(6, 6)).apply(L)
    # CLAHE doar unde exista structura: zonele plate (cer, rama, piele
    # neteda) raman line, altfel granulatia de polaroid devine muchii false
    cl = max(clarity, 0.5)
    sigma = max(2.0, min(L.shape) / 250.0)
    d = cv2.GaussianBlur(np.abs(lap), (0, 0), sigma)
    w = np.clip((d - 2.0 / cl) * cl / 5.0, 0.0, 1.0)
    w = cv2.GaussianBlur(w, (0, 0), sigma)
    Lf = w * Lc.astype(np.float32) + (1 - w) * L.astype(np.float32)
    # accentuare de muchii dozata de slider, tot doar pe structura
    blur = cv2.GaussianBlur(Lf, (0, 0), max(1.5, min(L.shape) / 400.0))
    Lf += 0.55 * cl * w * (Lf - blur)
    lab[..., 0] = np.clip(Lf, 0, 255).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


# ---------------------------------------------------------------- culori
def quantize(img: np.ndarray, n_colors: int, seed: int = 7):
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    cv2.setRNGSeed(seed)
    _, labels, centers = cv2.kmeans(lab, n_colors, None, criteria, 6,
                                    cv2.KMEANS_PP_CENTERS)
    centers_rgb = cv2.cvtColor(centers.reshape(-1, 1, 3).astype(np.uint8),
                               cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return labels.reshape(img.shape[:2]), centers_rgb, centers


# Papiotele reale din atelier: softbox Madeira Polyneon No.40 (decusut.ro,
# 40 de culori). Fisierele generate folosesc DOAR aceste fire, ca broderia
# fizica sa iasa 1:1 cu previzualizarea. RGB-urile vin din paleta Ink/Stitch.
POLYNEON_BOX = [
    ("1924", "Moonbeam", 251, 212, 0),
    ("1971", "Manila", 249, 179, 36),
    ("1866", "Pale Yellow", 240, 221, 145),
    ("1803", "Lily White", 237, 236, 223),
    ("1951", "Honeydew", 246, 153, 42),
    ("1765", "Pumpkin", 237, 112, 31),
    ("1678", "Fluorescent Orange", 237, 85, 46),
    ("1831", "Medium Purple", 154, 100, 156),
    ("1984", "Ruby Glint", 181, 41, 98),
    ("1990", "Ruby Glint Deschis", 216, 95, 149),
    ("1815", "Pink", 252, 190, 210),
    ("1637", "Warm Red", 188, 33, 48),
    ("1839", "Lipstick", 173, 29, 49),
    ("1981", "Wine", 135, 42, 57),
    ("1922", "Purple Accent", 77, 50, 117),
    ("1842", "Fire Blue", 0, 85, 149),
    ("1977", "Dark Turquoise", 0, 129, 175),
    ("1675", "Caribbean Blue", 122, 174, 213),
    ("1733", "Violet", 59, 123, 176),
    ("1743", "Light Navy", 47, 55, 92),
    ("1643", "Navy", 45, 53, 65),
    ("1902", "Mitchell Green", 45, 74, 56),
    ("1851", "Fleece Green", 0, 94, 56),
    ("1988", "Kelly", 0, 140, 67),
    ("1748", "Spruce", 169, 221, 118),
    ("1670", "Old Gold", 213, 167, 104),
    ("1673", "Beige", 173, 142, 94),
    ("1659", "Dark Oak", 82, 56, 52),
    ("1657", "Light Cocoa", 135, 91, 67),
    ("1885", "Tawny Birch", 160, 126, 97),
    ("1938", "Mushroom", 185, 169, 153),
    ("1682", "Taupe", 205, 191, 172),
    ("1800", "Black", 47, 48, 50),
    ("1946", "Neon Orange", 255, 97, 21),
    ("1823", "Yellow", 249, 255, 0),
    ("1850", "Green", 92, 202, 75),
    ("1640", "Twilight", 94, 97, 98),
    ("1918", "Limestone", 138, 139, 142),
    ("1687", "Vapor", 189, 197, 195),
    ("1801", "Barely Blue", 228, 232, 255),
]

_CHART = None


def thread_chart():
    """Firele din cutia Polyneon, ca obiecte EmbThread (construite o data)."""
    global _CHART
    if _CHART is None:
        _CHART = []
        for code, name, r, g, b in POLYNEON_BOX:
            t = EmbThread()
            t.set_color(r, g, b)
            t.description = name
            t.catalog_number = code
            t.brand = "Madeira Polyneon 40"
            _CHART.append(t)
    return _CHART


def match_threads(centers_rgb):
    """Fiecare culoare de cluster -> cel mai apropiat fir din cutia Polyneon."""
    charts = thread_chart()
    chart_rgb = np.array([[t.get_red(), t.get_green(), t.get_blue()] for t in charts],
                         np.uint8)
    chart_lab = cv2.cvtColor(chart_rgb.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB) \
                   .reshape(-1, 3).astype(np.float32)
    out = []
    for rgb in centers_rgb:
        lab = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
        d = ((chart_lab - lab) ** 2).sum(axis=1)
        out.append(charts[int(np.argmin(d))])
    return out


def match_gray_threads(vals):
    """Ca match_threads, dar doar printre firele neutre (gri) din paleta —
    altfel un gri inchis poate 'castiga' un fir maro."""
    charts = thread_chart()
    keep = []
    for t in charts:
        rgb = np.uint8([[[t.get_red(), t.get_green(), t.get_blue()]]])
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
        if math.hypot(lab[1] - 128, lab[2] - 128) < 8:
            keep.append((t, lab[0]))
    out = []
    for v in vals:
        lab = cv2.cvtColor(np.uint8([[v]]), cv2.COLOR_RGB2LAB)[0, 0]
        out.append(min(keep, key=lambda kl: abs(kl[1] - float(lab[0])))[0])
    return out


def lightness(rgb) -> float:
    return float(cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0, 0]) / 255 * 100


def accent_index(labels, centers_rgb, n):
    """Culoarea 'vedeta' a pozei: clusterul mare, saturat si central (nu
    fundal, nu margini/rama, nu alb/negru) — pentru stilurile minimaliste."""
    h, w = labels.shape
    my, mx = int(h * 0.12), int(w * 0.12)
    best, best_s = None, 0.0
    for i in range(n):
        m = labels == i
        share = float(m.mean())
        if share < 0.02:
            continue
        L = lightness(centers_rgb[i])
        if L > 88 or L < 15:
            continue
        lab = cv2.cvtColor(np.uint8([[centers_rgb[i]]]),
                           cv2.COLOR_RGB2LAB)[0, 0].astype(float)
        chroma = math.hypot(lab[1] - 128, lab[2] - 128)
        if chroma < 18:                  # accent doar daca exista culoare vie
            continue
        central = float(m[my:h - my, mx:w - mx].sum()) / max(float(m.sum()), 1.0)
        # accentul trebuie sa fie o pata compacta (frunza, obiect), nu un
        # inel/halou difuz de fundal: soliditate = arie / invelis convex
        num, cc, stats, cent = cv2.connectedComponentsWithStats(
            m.astype(np.uint8))
        if num < 2:
            continue
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = float(stats[big, cv2.CC_STAT_AREA])
        if area < 0.015 * h * w:
            continue
        cnts, _ = cv2.findContours((cc == big).astype(np.uint8),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = cv2.convexHull(np.vstack(cnts))
        solidity = area / max(float(cv2.contourArea(hull)), 1.0)
        if solidity < 0.45:
            continue
        cx, cy = cent[big]
        if not (0.2 * w < cx < 0.8 * w and 0.2 * h < cy < 0.8 * h):
            continue
        s = chroma * math.sqrt(share) * central * central
        if s > best_s:
            best, best_s = i, s
    return best


def dominant_angle(mask: np.ndarray, gray: np.ndarray) -> float:
    """Unghiul de umplere = perpendicular pe gradientul dominant (structure tensor)."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)
    m = mask > 0
    jxx, jyy = (gx[m] ** 2).sum(), (gy[m] ** 2).sum()
    jxy = (gx[m] * gy[m]).sum()
    if jxx + jyy < 1e-3:
        return 0.0
    ang = 0.5 * math.atan2(2 * jxy, jxx - jyy)      # directia gradientului
    deg = math.degrees(ang) + 90                     # firul merge de-a lungul muchiilor
    coherence = math.hypot(jxx - jyy, 2 * jxy) / (jxx + jyy)
    if coherence < 0.2:                              # zona fara directie clara
        return 0.0
    return ((deg + 90) % 180) - 90


def orientation_zones(mask, gray, base_angle, min_zone_mm2=60.0):
    """Imparte o regiune mare in zone dupa directia locala a texturii
    (structure tensor): firul 'curge' cu forma (par, falduri, acoperis),
    nu la un unghi unic. Regiunile mici sau fara directie raman intregi."""
    area_mm2 = float(mask.sum()) * MM_PER_PX * MM_PER_PX
    if area_mm2 < 400.0:
        return [(mask, base_angle)]
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)
    s = PX(3.0)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), s)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), s)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), s)
    coh = np.hypot(jxx - jyy, 2 * jxy) / (jxx + jyy + 1e-6)
    ang = np.degrees(0.5 * np.arctan2(2 * jxy, jxx - jyy)) + 90
    ang = (ang + 90) % 180 - 90              # directia de-a lungul structurii
    ok = (coh > 0.25) & (mask > 0)
    if ok.sum() < 0.25 * mask.sum():         # fara textura directionala clara
        return [(mask, base_angle)]
    bins = ((ang + 90) // 30).astype(np.int32).clip(0, 5)
    k5 = np.ones((5, 5), np.uint8)
    zones, rest = [], mask.copy()
    for b in range(6):
        zm = ((bins == b) & ok).astype(np.uint8)
        zm = cv2.morphologyEx(zm, cv2.MORPH_CLOSE, k5)
        zm = cv2.morphologyEx(zm, cv2.MORPH_OPEN, k5)
        zm = (zm & rest).astype(np.uint8)    # zonele nu se suprapun
        zm = drop_small_islands(zm, min_zone_mm2)
        if float(zm.sum()) * MM_PER_PX * MM_PER_PX < min_zone_mm2:
            continue
        zones.append((zm, b * 30 - 75.0))
        rest[zm > 0] = 0
    if not zones:
        return [(mask, base_angle)]
    zones.append((rest, base_angle))         # restul, pe unghiul de baza
    return zones


def fill_zones(mask, gray, base_angle, spacing_mm, stitch_mm, flow=True):
    """Umplere cu directie adaptata local (sau clasica, la unghi unic)."""
    zones = orientation_zones(mask, gray, base_angle) if flow \
        else [(mask, base_angle)]
    fills = []
    for zm, za in zones:
        fills.extend(fill_mask(zm, za, spacing_mm, stitch_mm))
    return fills


# ---------------------------------------------------------------- cusaturi
def drop_small_islands(mask, min_mm2=2.5):
    """Peticele izolate sub ~min_mm2 nu se pot coase curat: le scoatem."""
    n, lb, st, _ = cv2.connectedComponentsWithStats(mask)
    min_px = PX(1.0) * PX(1.0) * min_mm2
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < min_px:
            mask[lb == i] = 0
    return mask


def fill_mask(mask, angle_deg, spacing_mm, stitch_mm, tatami=True):
    """Umplere serpentina la unghi dat. Returneaza liste de trasee (in px 0.2mm)."""
    h, w = mask.shape
    diag = int(math.hypot(h, w)) + 2
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    M[0, 2] += (diag - w) / 2
    M[1, 2] += (diag - h) / 2
    rot = cv2.warpAffine(mask, M, (diag, diag), flags=cv2.INTER_NEAREST)
    Minv = cv2.invertAffineTransform(M)

    spacing = PX(spacing_mm)
    step = PX(stitch_mm)
    n, labels = cv2.connectedComponents(rot)
    paths = []
    for comp in range(1, n):
        cm = labels == comp
        ys, xs = np.where(cm)
        if len(ys) < PX(2) * PX(2):     # sub ~4mm^2 nu merita cusut
            continue
        path = []
        y = ys.min() + spacing / 2
        row_i = 0
        while y <= ys.max():
            r = cm[int(round(min(y, ys.max())))]
            idx = np.where(r)[0]
            if len(idx):
                # segmentele continue ale randului
                breaks = np.where(np.diff(idx) > 1)[0]
                segs = np.split(idx, breaks + 1)
                segs = [(s[0], s[-1]) for s in segs if (s[-1] - s[0]) >= PX(0.8)]
                if row_i % 2:
                    segs = [(b, a) for a, b in reversed(segs)]
                for x0, x1 in segs:
                    sgn = 1 if x1 >= x0 else -1
                    off = (step / 2) if (tatami and row_i % 2) else 0
                    xs_pts = [x0]
                    x = x0 + sgn * (step - off)
                    while (x1 - x) * sgn > step * 0.3:
                        xs_pts.append(x)
                        x += sgn * step
                    xs_pts.append(x1)
                    path.extend((xp, y) for xp in xs_pts)
            y += spacing
            row_i += 1
        if len(path) > 3:
            pts = np.array(path, np.float32)
            pts = pts @ Minv[:, :2].T + Minv[:, 2]
            paths.append(pts)
    return paths


def outline_mask(mask, step_mm=1.8, min_area_mm2=30):
    """Contur running-stitch in jurul regiunilor mari."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    step = PX(step_mm)
    paths = []
    for c in contours:
        if cv2.contourArea(c) < min_area_mm2 / (MM_PER_PX ** 2):
            continue
        c = c.reshape(-1, 2).astype(np.float32)
        d = np.r_[0, np.cumsum(np.hypot(*np.diff(c, axis=0).T))]
        if d[-1] < step * 2:
            continue
        t = np.arange(0, d[-1], step)
        path = np.c_[np.interp(t, d, c[:, 0]), np.interp(t, d, c[:, 1])]
        paths.append(np.vstack([path, path[:1]]))  # inchide conturul
    return paths


def resample(path, step_mm):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(path, axis=0).T))]
    if d[-1] < PX(step_mm) * 2:
        return None
    t = np.arange(0, d[-1], PX(step_mm))
    out = np.c_[np.interp(t, d, path[:, 0]), np.interp(t, d, path[:, 1])]
    return np.vstack([out, path[-1:]])


def _chain_edges(edges):
    """Pixelii de muchie -> lanturi ordonate de puncte (y, x)."""
    pts = set(zip(*np.where(edges > 0)))
    nbrs = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
    chains = []
    while pts:
        start = next(iter(pts))
        pts.discard(start)
        halves = []
        for _ in range(2):                     # mergem in ambele directii
            cur, half = start, []
            while True:
                nxt = next(((cur[0] + dy, cur[1] + dx) for dy, dx in nbrs
                            if (cur[0] + dy, cur[1] + dx) in pts), None)
                if nxt is None:
                    break
                half.append(nxt)
                pts.discard(nxt)
                cur = nxt
            halves.append(half)
        chains.append(halves[1][::-1] + [start] + halves[0])
    return chains


def _bridge_chains(chains, gap_px):
    """Uneste lanturile ale caror capete sunt foarte apropiate:
    fragmentele Canny devin o singura linie continua."""
    g2 = gap_px * gap_px
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(chains):
            j = i + 1
            while j < len(chains):
                a, b = chains[i], chains[j]
                merged = None
                for pa, pb, ra, rb in ((a[-1], b[0], False, False),
                                       (a[-1], b[-1], False, True),
                                       (a[0], b[0], True, False),
                                       (a[0], b[-1], True, True)):
                    dy, dx = pa[0] - pb[0], pa[1] - pb[1]
                    if dy * dy + dx * dx <= g2:
                        merged = (a[::-1] if ra else a) + (b[::-1] if rb else b)
                        break
                if merged is None:
                    j += 1
                else:
                    chains[i] = merged
                    del chains[j]
                    changed = True
            i += 1
    return chains


def _smooth(p, k=3):
    """Netezire usoara: dispar zimtii de pixel, linia curge."""
    if p is None or len(p) < 5:
        return p
    ker = np.ones(k, np.float32) / k
    q = p.copy()
    q[1:-1, 0] = np.convolve(p[:, 0], ker, "same")[1:-1]
    q[1:-1, 1] = np.convolve(p[:, 1], ker, "same")[1:-1]
    return q


def _cut_at_border(p, w, h, m=4):
    """Scoate portiunile care merg de-a lungul marginii imaginii
    (redundante cu rama cusuta)."""
    keep = (p[:, 0] > m) & (p[:, 0] < w - m) & (p[:, 1] > m) & (p[:, 1] < h - m)
    segs, cur = [], []
    for pt, k in zip(p, keep):
        if k:
            cur.append(pt)
        elif cur:
            segs.append(np.array(cur, np.float32))
            cur = []
    if cur:
        segs.append(np.array(cur, np.float32))
    return [s for s in segs if len(s) > 2]


def detect_faces(gray_u8):
    """Fetele din imagine (cascade Haar): acolo detaliile conteaza cel mai
    mult, deci desenul lor primeste tratament special."""
    try:
        casc = cv2.CascadeClassifier(cv2.data.haarcascades
                                     + "haarcascade_frontalface_default.xml")
        faces = casc.detectMultiScale(gray_u8, scaleFactor=1.1, minNeighbors=5,
                                      minSize=(int(PX(8)), int(PX(8))))
    except Exception:
        return []
    return [tuple(int(v) for v in f) for f in faces]


def sketch_paths(gray, min_mm=4.0, step_mm=1.4, faces=(), minimal=False):
    """Stil 'desen in linie': granitele formelor tonale mari dau linia
    structurala, continua; muchiile Canny adauga detaliile. Fragmentele
    apropiate se unesc, totul se netezeste. In zona fetei detaliile sunt
    mai sensibile si nu se filtreaza ca zgomot.
    minimal=True: doar muchiile lungi si clare (fara pragurile tonale, care
    pe fundaluri cu vinieta deseneaza inele) si fara liniile de la margine."""
    h, w = gray.shape[:2]
    g8 = gray.astype(np.uint8)
    g = cv2.GaussianBlur(g8, (3, 3), 0)
    paths, covered = [], np.zeros((h, w), np.uint8)
    face_mask = np.zeros((h, w), np.uint8)
    for fx, fy, fw, fh in faces:
        mx, my = int(fw * 0.1), int(fh * 0.1)
        face_mask[max(0, fy - my):fy + fh + my,
                  max(0, fx - mx):fx + fw + mx] = 1
    # 1) linia structurala: contururile formelor tonale mari
    sm = cv2.medianBlur(g, 9)
    grad = np.hypot(cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3),
                    cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3))
    # o granita reala are muchii Canny pe traseu; vinieta (gradient radial
    # lin) nu — altfel pragurile tonale deseneaza inele concentrice
    canny_sup = cv2.dilate(cv2.Canny(g, 35, 90),
                           np.ones((int(PX(0.8)) | 1,) * 2, np.uint8))
    k5 = np.ones((5, 5), np.uint8)
    qs = () if minimal else (0.45, 0.2, 0.7)
    grad_min, canny_min = 20.0, 0.25
    for q in qs:                             # intai forma principala
        t = float(np.quantile(sm, q))
        mask = (sm < t).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k5)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k5)
        mask = drop_small_islands(mask, 120.0)
        cnts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for c in cnts:
            if cv2.contourArea(c) < PX(1) * PX(1) * 80:
                continue                     # doar formele mari dau linia
            pts = c.reshape(-1, 2).astype(np.float32)
            iy, ix = pts[:, 1].astype(int), pts[:, 0].astype(int)
            if covered[iy, ix].mean() > 0.6:
                continue                     # granita desenata deja la alt prag
            if float(np.median(grad[iy, ix])) < grad_min:
                continue                     # pragul taie un gradient lin
                                             # (cer, umbra difuza): linie falsa
            if float((canny_sup[iy, ix] > 0).mean()) < canny_min:
                continue                     # fara suport de muchii: vinieta
            p = resample(np.vstack([pts, pts[:1]]), step_mm)
            if p is None:
                continue
            for s in _cut_at_border(p, w, h):
                if len(s) * step_mm >= min_mm:
                    paths.append(_smooth(s))
            cv2.polylines(covered, [pts.astype(np.int32)], True, 1,
                          thickness=max(3, int(PX(0.7))))
    # 2) detaliile: muchii Canny, fara cele acoperite de linia structurala
    edges = cv2.Canny(g, 35, 90)
    if face_mask.any():                  # pe fata: muchii mai sensibile
        edges |= cv2.Canny(g, 20, 60) & (face_mask * 255)
    k = int(PX(3)) | 1
    # densitatea se masoara inainte de suprimare: texturile raman texturi
    density = cv2.blur((edges > 0).astype(np.float32), (k, k))
    edges[covered > 0] = 0
    for chain in _bridge_chains(_chain_edges(edges), PX(1.0)):
        length_mm = len(chain) * MM_PER_PX
        on_face = bool(face_mask.any()) and \
            float(np.mean([face_mask[y, x] for y, x in chain[::4]])) > 0.5
        if length_mm < (2.5 if on_face else min_mm):
            continue
        # trasaturile fetei nu sunt zgomot; dar in modul minimalist filtram
        # peste tot — fetele fals-detectate (texturi, sclipici) ar scapa altfel
        if not on_face or minimal:
            # traseu intr-o zona plina de muchii = zgomot de textura
            dens = float(np.mean([density[y, x] for y, x in chain[::4]]))
            if length_mm < 9.0 and dens > 0.18:
                continue
            if length_mm < 25.0 and dens > 0.26:
                continue                 # nici fragmentele unite din texturi
            if dens > 0.32:
                continue                 # textura pura, oricat de lunga
        p = resample(np.array([(x, y) for y, x in chain], np.float32), step_mm)
        if p is not None:
            paths.append(_smooth(p))
    if minimal:
        # liniile lipite de marginea imaginii sunt rama/fundal, nu subiectul
        m = 0.05 * min(w, h)
        def _hugs_border(p):
            near = ((p[:, 0] < m) | (p[:, 0] > w - m)
                    | (p[:, 1] < m) | (p[:, 1] > h - m))
            return float(near.mean()) > 0.55
        paths = [p for p in paths if not _hugs_border(p)]
    return paths


def minimal_filter(paths, w, h, budget_mm=650.0, max_curl=2.2):
    """Pastreaza doar liniile definitorii pentru stilurile minimaliste:
    netede (nu 'crete' = textura), departe de resturile de rama, si doar
    pana la un buget total de fir — cele mai lungi si mai calme intai."""
    scored = []
    for p in paths:
        d = np.diff(p, axis=0)
        ln = float(np.hypot(d[:, 0], d[:, 1]).sum())
        bb = math.hypot(p[:, 0].max() - p[:, 0].min(),
                        p[:, 1].max() - p[:, 1].min())
        c = ln / max(bb, 1.0)
        if c > max_curl:
            continue                     # creata rau: zgomot de textura
        mx = 0.12                        # traseu integral intr-o banda de
        if p[:, 1].max() < h * mx or p[:, 1].min() > h * (1 - mx) \
           or p[:, 0].max() < w * mx or p[:, 0].min() > w * (1 - mx):
            continue                     # margine: rest de rama, nu subiect
        scored.append((ln / c, ln, p))
    scored.sort(key=lambda t: -t[0])     # lungi si netede intai
    out, total = [], 0.0
    for _, ln, p in scored:
        out.append(p)
        total += ln * MM_PER_PX
        if total > budget_mm:
            break
    return out


def split_long(paths, max_mm=8.0):
    """Sparge sariturile lungi dintre puncte consecutive ale unui traseu."""
    out = []
    lim = PX(max_mm)
    for p in paths:
        segs, cur = [], [p[0]]
        for a, b in zip(p, p[1:]):
            if math.dist(a, b) > lim:
                segs.append(np.array(cur)); cur = [b]
            else:
                cur.append(b)
        segs.append(np.array(cur))
        out.extend(s for s in segs if len(s) > 1)
    return out


def order_paths(paths, start=(0, 0)):
    """Ordonare greedy nearest-neighbor; traseul se poate coase si invers
    daca celalalt capat e mai aproape — sarituri cat mai scurte."""
    rest, ordered, pos = list(paths), [], np.array(start, np.float32)
    while rest:
        best = bi = None
        brev = False
        for k, p in enumerate(rest):
            d0 = float(np.hypot(*(p[0] - pos)))
            d1 = float(np.hypot(*(p[-1] - pos)))
            d, rev = (d0, False) if d0 <= d1 else (d1, True)
            if best is None or d < best:
                best, bi, brev = d, k, rev
        p = rest.pop(bi)
        if brev:
            p = p[::-1]
        ordered.append(p)
        pos = p[-1]
    return ordered


def jump_stats(color_plan):
    """Sariturile de fir dintre trasee consecutive (acelasi fir), in mm."""
    jumps = []
    for _, layers, _kind in color_plan:
        last = None
        for paths in layers:
            for p in paths:
                if last is not None:
                    jumps.append(math.dist(last, p[0]) * MM_PER_PX)
                last = p[-1]
    return jumps


# ---------------------------------------------------------------- asamblare
def merge_same_threads(color_plan):
    """Uneste blocurile consecutive care folosesc acelasi fir."""
    merged = []
    for thread, layers, kind in color_plan:
        if merged and merged[-1][0].catalog_number == thread.catalog_number \
                and merged[-1][2] == kind:
            merged[-1][1].extend(layers)
        else:
            merged.append((thread, list(layers), kind))
    return merged


def erase_lines(color_plan, em):
    """Sterge portiunile de linie pictate cu radiera in web. Doar straturile
    de linii (sketch, contururi, rama); umplerile raman intacte."""
    h, w = em.shape
    out = []
    for thread, layers, kind in color_plan:
        if kind != "line":
            out.append((thread, layers, kind))
            continue
        nl = []
        for paths in layers:
            np_ = []
            for p in paths:
                xi = np.clip(p[:, 0].astype(int), 0, w - 1)
                yi = np.clip(p[:, 1].astype(int), 0, h - 1)
                keep = ~em[yi, xi]
                run = []
                for pt, kp in zip(p, keep):
                    if kp:
                        run.append(pt)
                    else:
                        if len(run) > 2:
                            np_.append(np.array(run, np.float32))
                        run = []
                if len(run) > 2:
                    np_.append(np.array(run, np.float32))
            nl.append(np_)
        out.append((thread, nl, kind))
    return out


def build_pattern(color_plan, w_px, h_px):
    pat = pyembroidery.EmbPattern()
    cx, cy = w_px / 2, h_px / 2
    to_u = lambda p: (round((p[0] - cx) * MM_PER_PX * 10),
                      round((p[1] - cy) * MM_PER_PX * 10))
    first_color = True
    last = None
    for thread, layers, _kind in color_plan:
        if not any(layers):
            continue
        pat.add_thread(thread)
        if not first_color:
            pat.color_change()
            last = None
        first_color = False
        for paths in layers:
            for path in paths:
                # taiem firul doar cand saritura e prea lunga ca s-o ascundem
                if last is not None and math.dist(last, path[0]) > PX(6):
                    pat.trim()
                x, y = to_u(path[0])
                pat.add_stitch_absolute(pyembroidery.JUMP, x, y)
                for p in path:
                    x, y = to_u(p)
                    pat.add_stitch_absolute(pyembroidery.STITCH, x, y)
                last = path[-1]
        pat.trim()
        last = None
    pat.end()
    return pat


# ---------------------------------------------------------------- preview
def render_preview(color_plan, w_px, h_px, scale=1.0, fabric=(246, 243, 236)):
    """Randare 'realista': fiecare impunsatura e o linie cu umbra si variatie."""
    W, H = int(w_px * scale), int(h_px * scale)
    img = Image.new("RGB", (W, H), fabric)
    # textura discreta de panza
    rng = np.random.default_rng(3)
    small = np.array(img)[::3, ::3]
    noise = rng.integers(-4, 4, (*small.shape[:2], 1))
    tex = np.clip(small + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(cv2.resize(tex, (W, H), interpolation=cv2.INTER_LINEAR))
    dr = ImageDraw.Draw(img, "RGBA")

    w_main = max(2, int(PX(0.4) * scale))
    for thread, layers, _kind in color_plan:
        base = np.array([thread.get_red(), thread.get_green(), thread.get_blue()], float)
        shadow = tuple((base * 0.6).astype(int)) + (70,)
        for li, paths in enumerate(layers):
            for path in paths:
                pts = [(p[0] * scale, p[1] * scale) for p in path]
                for a, b in zip(pts, pts[1:]):
                    j = rng.uniform(0.92, 1.08)
                    col = tuple(np.clip(base * j, 0, 255).astype(int))
                    dr.line([(a[0] + 1, a[1] + 1), (b[0] + 1, b[1] + 1)],
                            fill=shadow, width=w_main)
                    dr.line([a, b], fill=col, width=w_main)
    return img


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("-o", "--out", default=None, help="prefix fisiere iesire")
    ap.add_argument("--size", type=float, default=95, help="latura design mm")
    ap.add_argument("--colors", type=int, default=7)
    ap.add_argument("--style", choices=["poster", "sketch", "mix", "color",
                                        "linie", "liniecolor", "duo", "tus"],
                    default="poster")
    ap.add_argument("--labels-out", action="store_true",
                    help="salveaza harta de regiuni (pt. editorul din web)")
    ap.add_argument("--labels-in", default="",
                    help="harta de regiuni editata (png; 255 = material gol)")
    ap.add_argument("--erase-mask", default="",
                    help="masca de radiera (png alb = liniile de sters)")
    ap.add_argument("--add-lines", default="",
                    help="linii desenate de mana in web (json, px de design)")
    ap.add_argument("--no-flow", action="store_true",
                    help="fara directie de fir adaptata local")
    ap.add_argument("--frame", choices=["none", "lines", "full"], default="none",
                    help="rama polaroid: doar linii sau plina, cusuta cu negru")
    ap.add_argument("--text", default="", help="text cusut in banda de jos a ramei")
    ap.add_argument("--text-size", type=float, default=7, help="inaltime text mm")
    ap.add_argument("--crop-rect", default="",
                    help="decupaj manual x,y,w,h (pixeli in imaginea originala)")
    ap.add_argument("--photo-rect", default="",
                    help="fotografia din rama x,y,w,h (pixeli, img. originala)")
    ap.add_argument("--detect-crop", action="store_true",
                    help="doar detecteaza decupajul si afiseaza JSON")
    ap.add_argument("--sat", type=float, default=1.25)
    ap.add_argument("--clarity", type=float, default=1.0,
                    help="intensitatea contrastului local (0.5 subtil - 2.5 puternic)")
    ap.add_argument("--despeckle", type=int, default=2)
    ap.add_argument("--spacing", type=float, default=0.45, help="dist. randuri mm")
    ap.add_argument("--stitch", type=float, default=3.0, help="lungime impunsatura mm")
    ap.add_argument("--skip-l", type=float, default=87,
                    help="culorile mai deschise de acest L* raman material gol")
    ap.add_argument("--no-crop", action="store_true")
    ap.add_argument("--no-underlay", action="store_true")
    a = ap.parse_args()

    out = a.out or os.path.splitext(a.image)[0] + "_brodat"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    img = np.array(ImageOps.exif_transpose(Image.open(a.image)).convert("RGB"))
    if a.detect_crop:
        x0, y0, x1, y1 = (int(v) for v in detect_crop_rect(img))
        cx0, cy0, cx1, cy1 = detect_card_rect(img, (x0, y0, x1, y1))
        print(json.dumps({
            "card": {"x": cx0, "y": cy0, "w": cx1 - cx0, "h": cy1 - cy0},
            "photo": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
            "iw": int(img.shape[1]), "ih": int(img.shape[0])}))
        return
    if a.text and a.frame == "none":
        a.frame = "lines"                # textul are nevoie de banda ramei
    if a.crop_rect:
        x, y, w, h = (max(0, int(v)) for v in a.crop_rect.split(","))
        img = img[y:y + h, x:x + w]
        r = None
        if a.photo_rect:
            px, py, pw, ph = (int(v) for v in a.photo_rect.split(","))
            r = photo_in_selection((px, py, pw, ph), x, y,
                                   img.shape[1], img.shape[0])
        if r is not None:                # selectie = polaroid cu margini:
            img = img[r[1]:r[3], r[0]:r[2]]   # coasem doar fotografia
        else:
            img = strip_border(img)
    elif not a.no_crop:
        img = crop_polaroid(img)
    Image.fromarray(img).save(out + "_crop.png")
    img = enhance(img, a.sat, a.clarity)
    Image.fromarray(img).save(out + "_enhanced.png")

    # geometrie: cu rama folosim proportiile reale de polaroid (88x107,
    # poza 79x79, banda lata jos), scalate ca inaltimea sa incapa in gherghef
    if a.frame != "none":
        f = a.size / 107.0
        inner_mm, ox_mm, oy_mm = 79 * f, 4.5 * f, 6 * f
        cw_px, ch_px = int(PX(88 * f)), int(PX(107 * f))
    else:
        inner_mm, ox_mm, oy_mm = a.size, 0, 0
        cw_px = ch_px = int(PX(a.size))
    size_px = int(PX(inner_mm))
    img = cv2.resize(img, (size_px, size_px), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)

    labels, centers_rgb, _ = quantize(img, a.colors)
    if a.labels_in:                      # harta editata de mana in web
        li = np.array(Image.open(a.labels_in))
        if li.ndim == 3:
            li = li[..., 0]
        if li.shape != labels.shape:
            li = cv2.resize(li, (labels.shape[1], labels.shape[0]),
                            interpolation=cv2.INTER_NEAREST)
        labels = li.astype(int)
    else:
        # despeckle: petele sub ~4mm^2 se topesc in culoarea din jur
        lab8 = labels.astype(np.uint8)
        for _ in range(a.despeckle):
            lab8 = cv2.medianBlur(lab8, 7)
        labels = lab8.astype(int)
    threads = match_threads(centers_rgb)
    if a.labels_out:
        Image.fromarray(labels.astype(np.uint8)).save(out + "_labels.png")
        with open(out + "_centers.json", "w") as f:
            json.dump({"colors": centers_rgb.astype(int).tolist(),
                       "threads": [{"code": str(t.catalog_number),
                                    "desc": t.description,
                                    "hex": "#%02x%02x%02x" % (
                                        t.get_red(), t.get_green(), t.get_blue())}
                                   for t in threads]}, f)

    faces = detect_faces(gray.astype(np.uint8))

    # ordine deschis -> inchis (detaliile inchise se cos deasupra)
    order = sorted(range(a.colors), key=lambda i: -lightness(centers_rgb[i]))

    quant = centers_rgb[np.clip(labels, 0, a.colors - 1)].astype(np.uint8)
    quant[labels == 255] = (246, 243, 236)      # gol = culoarea materialului
    Image.fromarray(quant).save(out + "_quant.png")

    color_plan, skipped = [], []
    k3 = np.ones((3, 3), np.uint8)

    if a.style in ("sketch", "mix"):
        dark_i = min(range(a.colors), key=lambda i: lightness(centers_rgb[i]))
        if a.style == "mix":
            # cinci benzi tonale de gri: zonele inchise isi pastreaza
            # structura, iar pielea/zonele luminoase primesc prezenta
            grays = match_gray_threads(np.array(
                [[28, 28, 32], [72, 71, 76], [115, 113, 118],
                 [165, 162, 167], [205, 202, 208]]))
            bounds = (30, 48, 65, 80, 88)
            spmul = (1.0, 1.0, 1.3, 1.7, 2.2)
            for i in order:
                L = lightness(centers_rgb[i])
                band = next((k for k, b in enumerate(bounds) if L < b), None)
                if band is None:
                    continue
                mask = (labels == i).astype(np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k3)
                mask = drop_small_islands(mask)
                if mask.sum() < PX(3) * PX(3):
                    continue
                ang = dominant_angle(mask, gray)
                sp = a.spacing * spmul[band]
                color_plan.append((grays[band],
                                   [order_paths(split_long(fill_zones(
                                       mask, gray, ang, sp, a.stitch,
                                       flow=not a.no_flow)))], "fill"))
        sk = order_paths(split_long(sketch_paths(gray, faces=faces)))
        if a.style == "sketch":          # linie 'de tus': cusuta de 3 ori
            sk = [np.vstack([p, p[::-1], p]) for p in sk]
        color_plan.append((threads[dark_i], [sk], "line"))
        order = []                       # sarim peste modul poster

    # stilurile minimaliste: putin fir, mult material vizibil
    if a.style in ("linie", "liniecolor", "duo", "tus"):
        dark = match_threads(np.array([[25, 24, 28]]))[0]
        if a.style == "tus":
            # pete 'de tus': doar zonele inchise, hasurate rar + contur.
            # pragul se calculeaza pe zona centrala (subiectul), nu pe
            # vinieta/rama, iar petele raman in interiorul cadrului
            k5 = np.ones((5, 5), np.uint8)
            hh, ww = gray.shape
            my, mx = int(hh * 0.08), int(ww * 0.08)
            core = gray[my:hh - my, mx:ww - mx]
            t = float(np.quantile(core, 0.35))
            mask = np.zeros((hh, ww), np.uint8)
            mask[my:hh - my, mx:ww - mx] = (core < t).astype(np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k5)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k5)
            mask = drop_small_islands(mask, 25.0)
            # petele care traiesc mai ales langa margine sunt fundal/vinieta
            band = np.ones_like(mask)
            band[int(hh * .18):hh - int(hh * .18),
                 int(ww * .18):ww - int(ww * .18)] = 0
            centru = np.zeros_like(mask)
            centru[int(hh * .25):hh - int(hh * .25),
                   int(ww * .25):ww - int(ww * .25)] = 1
            num, cc = cv2.connectedComponents(mask)
            for lbl in range(1, num):
                comp = cc == lbl
                if float(band[comp].mean()) > 0.5 \
                        or float(centru[comp].mean()) < 0.1:
                    mask[comp] = 0
            if mask.any():
                ang = dominant_angle(mask, gray)
                color_plan.append((dark, [order_paths(split_long(fill_mask(
                    mask, ang, a.spacing * 2.6, a.stitch,
                    tatami=False)))], "fill"))
                color_plan.append((dark, [order_paths(split_long(
                    outline_mask(mask, min_area_mm2=15)))], "line"))
        else:
            # doar muchiile lungi si clare, cusute plin (dus-intors-dus)
            sk_raw = sketch_paths(gray, min_mm=14.0, faces=faces, minimal=True)
            sk_raw = minimal_filter(sk_raw, size_px, size_px,
                                    budget_mm=inner_mm * 6.8)
            sk = order_paths(split_long(sk_raw))
            sk = [np.vstack([p, p[::-1], p]) for p in sk]
            ai = accent_index(labels, centers_rgb, a.colors) \
                if a.style in ("liniecolor", "duo") else None
            if a.style == "duo" and ai is not None:
                # un singur accent de culoare, umplut aerisit, sub linii
                mask = (labels == ai).astype(np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k3)
                mask = drop_small_islands(mask)
                if mask.sum() >= PX(3) * PX(3):
                    ang = dominant_angle(mask, gray)
                    color_plan.append((threads[ai], [order_paths(split_long(
                        fill_zones(mask, gray, ang, a.spacing * 2.0, a.stitch,
                                   flow=not a.no_flow)))], "fill"))
            thread = threads[ai] \
                if a.style == "liniecolor" and ai is not None else dark
            color_plan.append((thread, [sk], "line"))
        order = []

    for i in order:
        L = lightness(centers_rgb[i])
        if L >= a.skip_l:
            skipped.append((threads[i], L))
            continue
        mask = (labels == i).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k3)
        mask = drop_small_islands(mask)
        mask = cv2.dilate(mask, k3)          # compensare tragere fir (~0.2mm)
        if mask.sum() < PX(3) * PX(3):
            continue
        ang = dominant_angle(mask, gray)
        # culorile deschise (cer, fundal) se cos mai aerisit: material vizibil
        sp = a.spacing * (1 + max(0.0, (L - 65) / 30))
        layers = []
        if not a.no_underlay and sp < 0.6:   # underlay doar sub umplerile dense
            under = cv2.erode(mask, k3)
            layers.append(order_paths(split_long(
                fill_mask(under, ang + 90, 2.2, 4.5, tatami=False))))
        layers.append(order_paths(split_long(fill_zones(
            mask, gray, ang, sp, a.stitch, flow=not a.no_flow))))
        if L < 60:                       # contur doar pe zonele mari si inchise
            layers.append(order_paths(split_long(outline_mask(mask))))
        color_plan.append((threads[i], layers, "fill"))
        print(f"  culoare #{threads[i].catalog_number} {threads[i].description:<16}"
              f" L*={L:5.1f} unghi={ang:6.1f}  trasee="
              f"{sum(len(l) for l in layers)}")

    if a.style == "color":               # culori + desen in linie deasupra
        dark = match_threads(np.array([[25, 24, 28]]))[0]
        color_plan.append((dark, [order_paths(split_long(
            sketch_paths(gray, faces=faces)))], "line"))

    if a.frame != "none":
        # mutam designul in interiorul ramei si adaugam rama in negru
        off = np.array([PX(ox_mm), PX(oy_mm)], np.float32)
        color_plan = [(t, [[p + off for p in layer] for layer in layers], kind)
                      for t, layers, kind in color_plan]
        black = match_threads(np.array([[15, 15, 18]]))[0]
        ix0, iy0 = int(PX(ox_mm)), int(PX(oy_mm))
        ix1, iy1 = ix0 + size_px, iy0 + size_px
        flayers = []
        if a.frame == "full":
            band = np.ones((ch_px, cw_px), np.uint8)
            band[iy0:iy1, ix0:ix1] = 0
            flayers.append(order_paths(split_long(
                fill_mask(band, 0, a.spacing, a.stitch))))
        m = PX(0.6)
        for x0, y0, x1, y1 in ((m, m, cw_px - m, ch_px - m),
                               (ix0 - m, iy0 - m, ix1 + m, iy1 + m)):
            rect = np.array([[x0, y0], [x1, y0], [x1, y1],
                             [x0, y1], [x0, y0]], np.float32)
            p = resample(rect, 2.0)
            if p is not None:            # dus-intors: linie mai pronuntata
                flayers.append([p, p[::-1]])
        if a.text:
            tp, (tw, th) = text_paths(a.text, PX(a.text_size),
                                      cw_px - 2 * ix0 - PX(4))
            band_top, band_bot = iy1 + PX(1.5), ch_px - PX(1.5)
            toff = np.array([(cw_px - tw) / 2,
                             band_top + max(0, (band_bot - band_top - th) / 2)],
                            np.float32)
            flayers.append(order_paths([p + toff for p in tp]))
        color_plan.append((black, flayers, "line"))

    if a.add_lines and os.path.exists(a.add_lines):
        with open(a.add_lines) as f:
            added = json.load(f)
        line_threads = [t for t, _, k in color_plan if k == "line"]
        dark = line_threads[-1] if line_threads \
            else match_threads(np.array([[25, 24, 28]]))[0]
        apaths = []
        for pts in added:
            p = resample(np.array(pts, np.float32), 1.4)
            if p is not None:
                p = _smooth(p)
                apaths.append(np.vstack([p, p[::-1]]))   # dus-intors: vizibil
        if apaths:
            color_plan.append((dark, [order_paths(apaths)], "line"))

    if a.erase_mask and os.path.exists(a.erase_mask):
        em = np.array(Image.open(a.erase_mask).convert("L"))
        if em.shape != (ch_px, cw_px):
            em = cv2.resize(em, (cw_px, ch_px),
                            interpolation=cv2.INTER_NEAREST)
        color_plan = erase_lines(color_plan, em > 127)

    if a.labels_out:                     # date pt. radiera live din web:
        lines = [{"hex": "#%02x%02x%02x" % (t.get_red(), t.get_green(),
                                            t.get_blue()),
                  "paths": [np.round(p, 1).tolist()
                            for lay in layers for p in lay]}
                 for t, layers, kind in color_plan if kind == "line"]
        with open(out + "_lines.json", "w") as f:
            json.dump(lines, f)
        render_preview([e for e in color_plan if e[2] == "fill"],
                       cw_px, ch_px).save(out + "_fills.png")

    color_plan = merge_same_threads(color_plan)
    pat = build_pattern(color_plan, cw_px, ch_px)
    pyembroidery.write_pes(pat, out + ".pes")
    pyembroidery.write_dst(pat, out + ".dst")
    render_preview(color_plan, cw_px, ch_px).save(out + "_preview.png")

    n_st = pat.count_stitches()
    ext = pat.extents()
    w_mm, h_mm = (ext[2] - ext[0]) / 10, (ext[3] - ext[1]) / 10
    mins = n_st / 500 + pat.count_color_changes() * 0.5
    jumps = jump_stats(color_plan)
    long_j = [j for j in jumps if j > 5.0]
    with open(out + "_fire.txt", "w") as f:
        f.write(f"Design: {w_mm:.0f} x {h_mm:.0f} mm, {n_st} impunsaturi, "
                f"~{mins:.0f} min la 500 spm\n"
                f"Sarituri de fir >5mm: {len(long_j)} "
                f"(total {sum(long_j) / 10:.1f} cm de curatat)\n\n"
                f"Ordinea firelor (Madeira Polyneon No.40 — cutia de 40):\n")
        for k, (t, _, _kind) in enumerate(color_plan, 1):
            f.write(f" {k}. #{t.catalog_number:>3} {t.description}\n")
        for t, L in skipped:
            f.write(f"  (sarit, ramane materialul: {t.description}, L*={L:.0f})\n")
    print(f"\n{w_mm:.0f}x{h_mm:.0f} mm, {n_st} impunsaturi, {len(color_plan)} fire, "
          f"~{mins:.0f} min de coasere -> {out}.pes")


if __name__ == "__main__":
    main()
