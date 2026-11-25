"""DP Apply (TEST VERSION) - profile pictures for IDs without a DP.

Run via main.py mode 5. Reads output/browser_accounts.txt (the same
file every mode writes/reads through core.path_manager), opens each
account, and applies a photorealistic DP only where the ID has none.
IDs that already have a DP are skipped, never overwritten.

One account at a time, human behaviour throughout (shared helpers from
browser_register), a gap between accounts, one failure never stops the
batch, a checkpoint skips the account with no retry (stand-down rule).

TEST-VERSION HONESTY, UPDATED 2026-10-29: the DP upload selectors
below were LIVE-VERIFIED on a real ID (Sophia Wilson) on 2026-10-29:
Profile picture actions -> Choose profile picture -> file input
index 3 -> crop dialog -> Save, verified by the profile picture
changing and by the "updated profile picture" timeline post.
DP pictures come from FILES, not AI: automation/dp_pick picks
one photo per account from dp_pics/male/ or dp_pics/female/,
recognising the account's name (read from the profile) and
gender (About page first, first name second). No generation of
any kind runs in this mode.
"""

import base64
import json
import os
import random
import re
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from automation.browser_register import (
    _human_click,
    _human_pause,
    _human_type,
)
from automation.dp_pick import (
    detect_gender,
    dp_pics_dir,
    folder_status,
    pick_dp,
    record_used,
    used_file_path,
)
from core.path_manager import get_output_dir
from ui.colors import GREEN, RED, WHITE, YELLOW, CYAN

FB_PROFILE_URL = "https://www.facebook.com/profile.php?id={uid}"
FB_LOGIN_URL = "https://www.facebook.com/login"

# A custom photo is served from Facebook's user-content CDN. Default
# avatars come from the static CDN or carry one of these markers. Any
# unrecognised picture URL is treated as custom (skip = safe: missing
# one DP is harmless, overwriting an existing DP is not).
DEFAULT_DP_MARKERS = ("silhouette", "static.xx", "empty-profile", "default")


# --- accounts file (format: uid|password|cookies, one per line) ---


DP_COUNTRY = "US"
DP_GENERATED_DIR = Path(dp_pics_dir()) / "generated"
DP_GEN_MIN_BYTES = 10000
DP_HORDE_TIMEOUT_S = 150


_DP_COUNTRY_STYLE = {
    "US": {"people": "American", "hair": "brown",
           "skins": ("fair skin", "light skin", "fair skin",
                     "light-medium skin"),
           "street": "busy American city street",
           "market": "American farmers market",
           "landmark": "New York Brooklyn Bridge promenade with the Manhattan skyline",
           "clothes_f": "casual smart clothes",
           "market_clothes": "colorful casual shirt"},
    "UK": {"people": "British", "hair": "dark brown",
           "skins": ("fair skin", "fair skin", "light skin", "fair skin"),
           "street": "busy London street",
           "market": "London street market",
           "landmark": "London South Bank Thames riverside with Tower Bridge",
           "clothes_f": "casual smart clothes",
           "market_clothes": "colorful casual shirt"},
    "IN": {"people": "Indian", "hair": "black",
           "skins": ("fair skin", "wheatish skin", "medium-brown skin",
                     "dusky skin"),
           "street": "busy Indian street",
           "market": "vibrant Indian market",
           "landmark": "Kolkata Hooghly riverfront promenade with the Howrah Bridge",
           "clothes_f": "kurta or casual Indian street clothes",
           "market_clothes": "colorful kurta"},
    "EU": {"people": "European", "hair": "brown",
           "skins": ("fair skin", "light skin", "fair skin", "light skin"),
           "street": "busy European city street",
           "market": "European street market",
           "landmark": "Paris Seine riverside with the Eiffel Tower",
           "clothes_f": "casual smart clothes",
            "market_clothes": "colorful casual shirt"},
    "AU": {"people": "Australian", "hair": "light brown",
           "skins": ("fair skin", "sun-kissed skin", "fair skin",
                     "light skin"),
           "street": "busy Australian city street",
           "market": "Australian weekend market",
           "landmark": "Sydney Circular Quay harbour with the Opera House and Harbour Bridge",
           "clothes_f": "casual smart clothes",
           "market_clothes": "colorful casual shirt"},
    "SG": {"people": "Singaporean", "hair": "black",
           "skins": ("fair skin", "light-medium skin", "fair skin",
                     "light skin"),
           "street": "busy Singapore street",
           "market": "Singapore street market",
           "landmark": "Singapore Marina Bay promenade with Marina Bay Sands",
           "clothes_f": "casual smart clothes",
           "market_clothes": "colorful casual shirt"},
}


_DP_FACE_STRICT = (
    "natural realistic face, two open eyes both fully formed, one straight correctly proportioned nose, two complete ears both fully formed and fully visible, slight natural asymmetry like a real person's face, real skin texture with visible pores, natural skin imperfections, slight blemishes, all facial features complete, nothing missing, nothing deformed, nothing distorted, not plastic skin, not a mask-like face, not airbrushed, no beauty filter, no skin smoothing, not doll-like")


_FACE_VAR_M = (
    "oval face, deep-set eyes, thick eyebrows, straight nose",
    "square face, strong cheekbones, sharp eyes, defined jawline",
    "round face, warm eyes, full lips, gentle smile",
    "angular face, prominent nose, arched eyebrows, slight smile",
    "long face, almond-shaped eyes, high cheekbones, neutral expression",
    "heart-shaped face, large eyes, straight eyebrows, dimples when smiling",
    "wide jaw, deep-set eyes, thick eyebrows, a small mole on the cheek",
    "narrow face, sharp eyes, straight nose, cleft chin",
    "oval face, hooded eyes, strong cheekbones, full lips",
    "square face, warm eyes, arched eyebrows, freckles across the nose",
    "round face, large eyes, thick eyebrows, high cheekbones",
    "angular face, deep-set eyes, prominent nose, slight smile",
)


_FACE_VAR_F = (
    "oval face, large almond-shaped eyes, arched eyebrows, full lips",
    "round face, warm eyes, gentle smile, dimples",
    "heart-shaped face, deep-set eyes, high cheekbones, straight nose",
    "square face, sharp eyes, defined cheekbones, gentle smile",
    "long face, almond-shaped eyes, arched eyebrows, a small mole on the cheek",
    "oval face, large eyes, thick eyebrows, full lips",
    "round face, warm eyes, freckles across the nose, gentle smile",
    "heart-shaped face, deep-set eyes, high cheekbones, neutral expression",
    "square face, almond-shaped eyes, straight eyebrows, dimples",
    "long face, large eyes, arched eyebrows, full lips",
    "oval face, warm eyes, high cheekbones, a small mole on the chin",
    "round face, deep-set eyes, thick eyebrows, gentle smile",
)


_DP_PERSONA_M = (
    "32-year-old man with a short black beard and mustache, round face, thick eyebrows, warm friendly smile",
    "29-year-old man with thin round glasses, long narrow face, clean-shaven, side-parted hair, calm neutral expression",
    "34-year-old man with thick curly hair, square jaw face, light stubble beard, freckles across the nose, slight smile",
    "30-year-old man with a short boxed beard, oval face, deep-set eyes, straight nose, relaxed smile",
    "36-year-old man, clean-shaven, broad face, short grey-flecked hair, gentle smile",
    "28-year-old man with a light stubble beard, long face, prominent cheekbones, wavy dark hair, neutral expression",
)


_DP_PERSONA_F = (
    "30-year-old woman with long straight black hair, oval face, soft smile",
    "28-year-old woman with shoulder-length curly brown hair, round face, freckles, warm smile",
    "33-year-old woman with a short bob haircut, heart-shaped face, gentle smile",
    "31-year-old woman with long wavy blonde hair, long face, calm expression",
    "29-year-old woman with black hair in a low ponytail, square face, thick eyebrows, friendly smile",
    "35-year-old woman with short pixie hair, oval face, subtle smile",
)


_CLOTHES_M = (
    "wearing a charcoal button-up shirt and blue jeans",
    "wearing a white t-shirt and black jeans",
    "wearing a blue checked shirt and dark jeans",
    "wearing a black polo shirt and charcoal trousers",
    "wearing a navy blue shirt and beige chinos",
    "wearing a green casual shirt and blue jeans",
    "wearing a maroon button-up shirt and black jeans",
    "wearing a light blue shirt and dark trousers",
)


_CLOTHES_F = (
    "wearing a white kurta and white pajama",
    "wearing a floral summer dress",
    "wearing a red blouse and blue jeans",
    "wearing a black top and white trousers",
    "wearing a pink kurta and leggings",
    "wearing a green dress",
    "wearing a blue shirt and jeans",
    "wearing a yellow top and black pants",
)


_DP_NEGATIVE_PROMPT = (
    "deformed, distorted, disfigured, bad anatomy, missing eye, missing eyes, extra eye, extra eyes, missing ear, missing ears, extra ear, deformed ear, broken ear, long nose, missing nose, deformed nose, extra nose, asymmetric face, asymmetric eyes, crossed eyes, closed eyes, duplicate face, mutated, blurry, out of focus, low quality, watermark, text, logo, cartoon, painting, illustration, ugly, split image, diptych, collage, side profile, back view")


_HORDE_ANON_KEY = "0000000000"


_POLLINATIONS_API_TOKEN_XOR = "KTEFLRAKDzQOaW9pA2xtGwtjLxMyMQsWHRYzAyA5DisUNTU="


_DP_LAST_PIC = [None]


_DP_LAST_GEN_ERROR = [""]
def _dp_horde_apikey():
    """AI Horde key: a registered key from env AIHORDE_API_KEY
    (free registration, no card — slightly better queue priority),
    else the anonymous key. Both are watermark-free."""
    _k = os.environ.get("AIHORDE_API_KEY", "").strip()
    return _k or _HORDE_ANON_KEY

_CLOUDFLARE_XOR_KEY = 0x5A
_CLOUDFLARE_ACCOUNT_ID_XOR = "P2M5bWk8O21tbm4+OW9uOWI7aTtiP21jbGlqOWJrbm8="
_CLOUDFLARE_API_TOKEN_XOR = "OTwvLgUxPSMRHBwIEDsRGygubTYeMDMDKA5rFSwxHwouEmssFRMYHAIxFywIOWNia205bGo="


_POLLINATIONS_XOR_KEY = 0x5A


def _pollinations_baked_token():
    """Decode the baked-in Pollinations API token. Returns the
    token or None when undecodable."""
    try:
        import base64
        return bytes(
            b ^ _POLLINATIONS_XOR_KEY
            for b in base64.b64decode(_POLLINATIONS_API_TOKEN_XOR)
        ).decode("ascii") or None
    except Exception:
        return None


def _cloudflare_baked_creds():
    """Decode the baked-in Cloudflare credentials (Account ID + API
    token). Returns (account_id, token) or (None, None) when
    undecodable. Mirrors _pollinations_baked_token (same base64 +
    single-byte XOR 0x5A pattern)."""
    try:
        import base64
        _aid = bytes(
            b ^ _CLOUDFLARE_XOR_KEY
            for b in base64.b64decode(_CLOUDFLARE_ACCOUNT_ID_XOR)
        ).decode("ascii")
        _tok = bytes(
            b ^ _CLOUDFLARE_XOR_KEY
            for b in base64.b64decode(_CLOUDFLARE_API_TOKEN_XOR)
        ).decode("ascii")
        return (_aid or None, _tok or None)
    except Exception:
        return (None, None)
def _dp_pollinations_token():
    """Pollinations API token: env POLLINATIONS_API_KEY, else
    ~/.pollinations_api_key, else the BAKED-IN token (Afnan
    2026-11-13 — permanent, no per-user setup). Returns the token
    or None when no source yields one. A token is REQUIRED for a
    watermark-free image; without one Pollinations watermarks."""
    _tok = os.environ.get("POLLINATIONS_API_KEY", "").strip()
    if not _tok:
        try:
            _tok = (Path.home() / ".pollinations_api_key").read_text().strip()
        except Exception:
            _tok = ""
    if not _tok:
        _tok = _pollinations_baked_token() or ""
    return _tok or None
def _dp_gen_providers():
    """DP generation providers in fallback order (watermark-free
    only). AI Horde first (registered key when AIHORDE_API_KEY is
    set, else anonymous), then anonymous Horde if a registered key
    was tried, then Pollinations klein (Bearer token, baked-in).
    Pollinations is live-proven 2026-11-13: klein, 1024x1024 square,
    private=true, no watermark with a token. Cloudflare
    FLUX.1-schnell is DELIBERATELY NOT here: Afnan 2026-11-13
    ("Istarha ki DPs mare accounts ko kha jain gi") — FLUX
    portraits look obviously AI-generated and a detectable DP
    risks the whole account being flagged/banned. A missing DP
    ("no pic available") is safe; a fake-looking DP is not.
    _dp_gen_cloudflare + the baked-in creds stay in the code
    (unused) so Cloudflare can be re-enabled in one line."""
    providers = [("AI Horde", lambda p: _dp_gen_horde(p))]
    if _dp_horde_apikey() != _HORDE_ANON_KEY:
        providers.append(
            ("AI Horde (anonymous)",
             lambda p: _dp_gen_horde(p, _HORDE_ANON_KEY)))
    providers.append(("Pollinations", lambda p: _dp_gen_pollinations(p)))
    return providers
def _dp_gen_prompt(gender):
    if gender not in ("male", "female"):
        raise ValueError(f"_dp_gen_prompt: unknown gender {gender!r}")
    if DP_COUNTRY not in _DP_COUNTRY_STYLE:
        raise ValueError(f"_dp_gen_prompt: unknown country {DP_COUNTRY!r}")
    style = _DP_COUNTRY_STYLE[DP_COUNTRY]
    people = style["people"]
    hc = style["hair"]
    skins = style["skins"]
    person = "man" if gender == "male" else "woman"
    _is_male = (gender == "male")
    _hm = ("short neat {hc} hair",
           "textured medium-length {hc} hair",
           "thick curly {hc} hair",
           "side-parted {hc} hair",
           "short textured {hc} hair",
           "spiky textured {hc} hair",
           "medium-length swept-back {hc} hair",
           "short cropped {hc} hair")
    _hf = ("shoulder-length straight {hc} hair",
           "long wavy {hc} hair over one shoulder",
           "thick curly {hc} hair tied back loosely",
           "{hc} hair in a neat bun",
           "shoulder-length wavy {hc} hair",
           "curly shoulder-length {hc} hair",
           "long straight {hc} hair with a center part",
           "short bob-cut {hc} hair")
    _hair = [(_hm[i] if _is_male else _hf[i]).format(hc=hc)
             for i in range(8)]
    _face = (f"{_DP_FACE_STRICT}, clearly {people} facial features, "
             f"{random.choice(_FACE_VAR_M if _is_male else _FACE_VAR_F)}, "
             "facing the camera directly, looking straight at the camera, "
             "front-facing portrait, full face visible, both eyes looking at the camera, "
             "one single person only in the frame, no split image, no diptych, "
             "no collage, no side profile, no back view")
    _geo = ("square frame, whole person centered, full body visible "
            "from head to toe, camera about 4 meters away at waist "
            "height, head near top of frame, feet near bottom of frame, "
            "background on both sides, nothing cropped")
    _cam = ("shot on iPhone, real smartphone photo, natural phone "
            "camera look, deep depth of field, background and subject "
            "both in focus, background people, shops, trees and objects "
            "as sharp, clear and detailed as the person, same realism "
            "throughout, no bokeh, no background blur, no shallow depth "
            "of field, everything in focus from foreground to background, "
            "soft overcast daylight, natural sensor noise, realistic "
            "textures everywhere, no AI smoothness, no painterly "
            "background")
    _skin = ("natural unretouched skin, subtle pores, slight tonal "
             "variation, flyaway hairs, small believable imperfections, "
             "no makeup, natural bare lips, both eyes the same size")
    _real = ("authentic real photograph, looks like a genuine candid "
             "photo from a real person's phone gallery, not AI-generated, "
             "not a digital render, not retouched, clear depth in three "
             "layers — foreground, midground and background all in focus, "
             "people at different distances, everything as detailed as "
             "the person")
    _who = random.choice(_DP_PERSONA_M if _is_male else _DP_PERSONA_F)
    _clothes = random.choice(_CLOTHES_M if _is_male else _CLOTHES_F)
    _act = ("sitting relaxed, natural posture, hands resting naturally",
            "sitting at a desk, looking at a laptop naturally",
            "sitting on a bench, relaxed, looking around naturally",
            "standing naturally, relaxed posture, hands at sides")
    variants = (
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[0]}, {_hair[0]}, {_act[0]}, {_geo}, {_cam}, {_skin}, {_real}, sitting in a modern hotel lobby, comfortable armchair, elegant interior with warm lights and people around, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[1]}, {_hair[1]}, {_act[1]}, {_geo}, {_cam}, {_skin}, {_real}, sitting at a desk in a modern office, laptop open, glass walls and desks in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[2]}, {_hair[2]}, {_act[2]}, {_geo}, {_cam}, {_skin}, {_real}, sitting on a bench in a green park, trees and walking paths in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[3]}, {_hair[3]}, {_act[0]}, {_geo}, {_cam}, {_skin}, {_real}, sitting at a table in a modern cafe, coffee cup on the table, warm lights and people around, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[0]}, {_hair[4]}, {_act[0]}, {_geo}, {_cam}, {_skin}, {_real}, sitting at a table in a modern restaurant, warm ambient lighting and tables in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[1]}, {_hair[5]}, {_act[3]}, {_geo}, {_cam}, {_skin}, {_real}, standing in a modern shopping mall, shops and people in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[2]}, {_hair[6]}, {_act[1]}, {_geo}, {_cam}, {_skin}, {_real}, sitting in a modern co-working space, desks and laptops around, people working in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[3]}, {_hair[7]}, {_act[3]}, {_geo}, {_cam}, {_skin}, {_real}, standing by a railing on a riverside promenade, hands in pockets, {style['landmark']}, people walking at different distances in the midground, river and landmark in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
        f"Full body shot, whole person visible from head to toe, Photorealistic candid photo of a handsome {people} {person} in their early 30s, {_who}, {_face}, {_clothes}, {skins[0]}, {_hair[2]}, {_act[3]}, {_geo}, {_cam}, {_skin}, {_real}, standing on a busy modern city street, {style['street']} shops with signage and people in the background, doing something natural in a real place, modern everyday life, sharp and clear, in focus, not blurry, not soft-focus, background in sharp focus with people and objects clearly visible, not blurred, not hidden, no bokeh, no beauty filter, no skin smoothing, unedited raw photo, whole person visible in frame, no text, no watermark, not a studio portrait",
    )
    return random.choice(variants)


def _dp_download_bytes(url, headers, timeout_s):
    last_err = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                if getattr(resp, "status", 200) != 200:
                    return None
                return resp.read()
        except Exception as e:
            last_err = e
            time.sleep(2)
    print(f"  dp: download failed — {str(last_err)[:80]}")
    return None


def _dp_valid_image(data):
    if not data or len(data) < DP_GEN_MIN_BYTES:
        return False
    return (data[:3] == b"\xff\xd8\xff"
            or data[:8] == b"\x89PNG\r\n\x1a\n"
            or data[:4] == b"RIFF")


def _dp_gen_pollinations(prompt):
    """Generate a DP via Pollinations (klein model, gen endpoint).
    Watermark-free ONLY with a Bearer token (see
    _dp_pollinations_token); anonymous calls are watermarked and
    are never used here. Live-proven 2026-11-13: klein, 1024x1024
    square (Facebook DP size, 1:1), private=true, random seed per
    call (same prompt+seed returns the cached image). Returns
    image bytes or None."""
    token = _dp_pollinations_token()
    if not token:
        return None
    try:
        import urllib.parse
        seed = random.randint(1, 999999)
        url = ("https://gen.pollinations.ai/image/"
               f"{urllib.parse.quote(prompt)}"
               f"?model=klein&width=1024&height=1024&seed={seed}"
               f"&private=true")
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read(20 * 1024 * 1024)
    except Exception as e:
        _DP_LAST_GEN_ERROR[0] = "Pollinations failed"
        print(f"  dp: Pollinations request failed — {str(e)[:80]}")
        return None
    if data and _dp_valid_image(data):
        return data
    _DP_LAST_GEN_ERROR[0] = "Pollinations returned no usable image"
    print("  dp: Pollinations returned no usable image")
    return None


def _dp_gen_horde(prompt, apikey=None):

    if apikey is None:
        apikey = _dp_horde_apikey()
    try:
        payload = json.dumps({
            "prompt": prompt + " ### " + _DP_NEGATIVE_PROMPT,
            "params": {"width": 1024, "height": 1024, "steps": 25, "n": 1,
                       "sampler_name": "k_euler", "cfg_scale": 7.0},
            "nsfw": False, "censor_nsfw": False, "trusted_workers": False,
            "models": ["Juggernaut XL"],
        }).encode()
        sub = None
        last_err = None
        for _submit_attempt in range(2):
            try:
                req = urllib.request.Request(
                    "https://stablehorde.net/api/v2/generate/async",
                    data=payload,
                    headers={"Content-Type": "application/json",
                             "apikey": apikey},
                    method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    sub = json.loads(resp.read())
                break
            except Exception as e:
                last_err = e
                try:
                    body = e.read().decode("utf-8", "ignore")[:200]
                except Exception:
                    body = ""
                print(f"  dp: AI Horde submit failed "
                    f"({str(e)[:60]}; body={body!r}) — "
                    f"{'retrying once' if _submit_attempt == 0 else 'giving up'}")
                time.sleep(2)
        if sub is None:
            _DP_LAST_GEN_ERROR[0] = "AI Horde submit failed"
            print(f"  dp: AI Horde submit failed twice — {str(last_err)[:80]}")
            return None
        gid = (sub or {}).get("id")
        if not gid:
            _DP_LAST_GEN_ERROR[0] = "AI Horde gave no generation id"
            print(f"  dp: AI Horde gave no generation id (response={str(sub)[:120]})")
            return None
        done = False
        deadline = time.time() + DP_HORDE_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(10)
            req = urllib.request.Request(
                f"https://stablehorde.net/api/v2/generate/check/{gid}",
                headers={"apikey": apikey})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    st = json.loads(resp.read())
            except Exception:
                continue
            if (st or {}).get("done"):
                done = True
                break
        if not done:
            _DP_LAST_GEN_ERROR[0] = "AI Horde timed out"
            print("  dp: AI Horde timed out waiting for the image")
            return None
        req = urllib.request.Request(
            f"https://stablehorde.net/api/v2/generate/status/{gid}",
            headers={"apikey": apikey})
        with urllib.request.urlopen(req, timeout=30) as resp:
            fin = json.loads(resp.read())
        gens = (fin or {}).get("generations") or []
        if not gens:
            _DP_LAST_GEN_ERROR[0] = "AI Horde finished with no image"
            print("  dp: AI Horde finished with no image")
            return None
        img_url = gens[0].get("img")
        if not img_url:
            return None
        data = _dp_download_bytes(
            img_url, {"User-Agent": "Mozilla/5.0"}, 60)
        if data and _dp_valid_image(data):
            return data
        _DP_LAST_GEN_ERROR[0] = "AI Horde returned no usable image"
        print("  dp: AI Horde returned no usable image")
        return None
    except Exception as e:
        try:
            body = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            body = ""
        _DP_LAST_GEN_ERROR[0] = "AI Horde failed"
        print(f"  dp: AI Horde failed — {str(e)[:80]}; body={body!r}")
        return None


def _dp_gen_kavel(prompt):
    try:
        anon = "fb-ec2-" + uuid.uuid4().hex[:12]
        headers = {
            "content-type": "application/json",
            "x-anon-id": anon,
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/157.0.0.0 Safari/537.36"),
            "Origin": "https://www.kavel.ai",
            "Referer": "https://www.kavel.ai/",
        }
        body = json.dumps({
            "provider": "kie", "mediaType": "image",
            "model": "kavel-image-v1", "scene": "text-to-image",
            "prompt": prompt, "options": {"aspect_ratio": "1:1"},
        }).encode()
        req = urllib.request.Request(
            "https://www.kavel.ai/api/ai/generate", data=body,
            headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            sub = json.loads(resp.read())
        data = (sub or {}).get("data") or {}
        if data.get("wall"):
            print(f"  dp: Kavel out of credit ({data.get('reason')})")
            return None
        tid = data.get("id")
        if not tid:
            print("  dp: Kavel gave no task id")
            return None
        status = ""
        st = {}
        deadline = time.time() + DP_KAVEL_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(12)
            req = urllib.request.Request(
                "https://www.kavel.ai/api/ai/anon-query"
                f"?taskId={tid}&provider=kie&mediaType=image",
                headers={"x-anon-id": anon,
                         "User-Agent": headers["User-Agent"]})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    st = json.loads(resp.read())
            except Exception:
                continue
            status = ((st or {}).get("data") or {}).get("status", "")
            if status in ("success", "failed"):
                break
        if status != "success":
            print(f"  dp: Kavel did not finish (status={status or 'timeout'})")
            return None
        imgs = ((st or {}).get("data") or {}).get("images") or []
        if not imgs:
            print("  dp: Kavel finished with no image")
            return None
        data = _dp_download_bytes(
            imgs[0], {"User-Agent": "Mozilla/5.0"}, 60)
        if data and _dp_valid_image(data):
            return data
        print("  dp: Kavel returned no usable image")
        return None
    except Exception as e:
        print(f"  dp: Kavel failed — {str(e)[:80]}")
        return None


def _dp_generate_pic(gender, uid=None):
    if gender not in ("male", "female"):
        return None
    prompt = _dp_gen_prompt(gender)
    data = None
    for _pname, _pfn in _dp_gen_providers():
        try:
            data = _pfn(prompt)
        except Exception as e:
            print(f"  dp: {_pname} raised — {str(e)[:80]}")
            data = None
        if data:
            print(f"  dp: generated via {_pname} ({len(data)} bytes)")
            break
        print(f"  dp: {_pname} gave nothing — trying next provider")
    if not data:
        print("  dp: all DP providers failed — skipping DP")
        return None
    if data[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    else:
        ext = ".jpg"
    try:
        DP_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        stem = f"gen_{DP_COUNTRY}_{gender}_{uid}" if uid else f"gen_{DP_COUNTRY}_{gender}"
        path = DP_GENERATED_DIR / f"{stem}_{secrets.token_hex(6)}{ext}"
        path.write_bytes(data)
        return str(path)
    except Exception as e:
        print(f"  dp: could not save generated DP — {str(e)[:80]}")
        try:
            if "path" in locals() and path.exists():
                path.unlink()
        except Exception:
            pass
        return None

def parse_accounts_file(path):
    accounts = []
    if not os.path.exists(path):
        return accounts
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 2:
                continue
            accounts.append({
                "uid": parts[0].strip(),
                "password": parts[1].strip(),
                "cookies": parts[2].strip() if len(parts) > 2 else "",
            })
    return accounts


def parse_cookie_string(raw, domain):
    """Parse cookies in ANY common format into Playwright cookie dicts.

    Handles: JSON array/dict (browser-extension exports like
    EditThisCookie / Cookie-Editor), Netscape cookies.txt
    (tab-separated), and name=value text separated by ';', '|'
    or newlines (with an optional leading 'Cookie:' label).
    Set-Cookie attribute pairs (expires/path/domain/...) are
    skipped. Returns a list of {name, value, domain, path}."""
    import json as _json
    raw = (raw or "").strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    if not raw:
        return []
    default_domain = domain or ".facebook.com"
    out = []
    seen = set()
    _skip = {"expires", "max-age", "path", "domain", "secure",
             "httponly", "samesite", "version", "comment"}

    def _add(name, value, dom=None, path="/"):
        name = str(name or "").strip().strip('"').strip("'")
        value = str(value or "").strip().strip('"').strip("'")
        if not name or name.lower() in _skip:
            return
        d = str(dom or default_domain).strip() or default_domain
        key = (name, d)
        if key in seen:
            return
        seen.add(key)
        out.append({"name": name, "value": value,
                    "domain": d, "path": path or "/"})

    # 1) JSON: array of cookie objects, single object, or name->value map
    if raw[:1] in ("[", "{"):
        try:
            data = _json.loads(raw)
            if isinstance(data, dict):
                if any(str(k).lower() in ("name", "value") for k in data):
                    data = [data]
                else:
                    for k, v in data.items():
                        _add(k, v)
                    return out
            if isinstance(data, list):
                for c in data:
                    if not isinstance(c, dict):
                        continue
                    low = {str(k).lower(): v for k, v in c.items()}
                    _add(low.get("name"), low.get("value"),
                         low.get("domain") or low.get("host"),
                         low.get("path", "/"))
                return out
        except Exception:
            pass

    # 2) Netscape cookies.txt: tab-separated, >=7 fields per line
    lines = [ln for ln in raw.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    if lines and all("\t" in ln for ln in lines):
        rows = []
        ok = True
        for ln in lines:
            parts = ln.split("\t")
            if len(parts) < 7:
                ok = False
                break
            rows.append((parts[5], parts[6], parts[0], parts[2]))
        if ok:
            for nm, val, dom, pth in rows:
                _add(nm, val, dom, pth)
            return out

    # 3) name=value text separated by ';', '|' or newlines
    text = raw.replace("\r", "\n").replace("|", ";").replace("\n", ";")
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        _add(name, value)
    return out


def has_c_user(cookies):
    return any(c["name"] == "c_user" and c["value"] for c in cookies)


def _is_logged_in(page, ctx):
    """True only for a real logged-in session. Cookie presence alone
    proves nothing: dead cookies stay in the jar, and a logged-out
    profile page still shows the person's name in h1 - so the old
    check (c_user + name) passed for dead sessions and the password
    fallback never ran. A logged-out page always shows a Log in
    control; a logged-in session never does - that is the
    discriminator."""
    if not has_c_user(ctx.cookies()):
        return False
    if not read_profile_name(page):
        return False
    for role in ("link", "button"):
        try:
            if page.get_by_role(role, name="Log in").first.is_visible():
                return False
        except Exception:
            pass
    return True


# --- profile reading ---


def _looks_like_name(text):
    """A display name: 1-4 words of letters, spaces, hyphens,
    apostrophes, periods. Rejects Facebook chrome labels."""
    if not text or len(text) > 60:
        return False
    low = text.strip().lower()
    if low in ("facebook", "home", "notifications", "log in", "sign up",
               "see more on facebook", "edit profile", "add to story",
               "add cover photo"):
        return False
    if not re.fullmatch(r"[A-Za-z\u00c0-\u00ff'\u2019. -]+",
                        text.strip()):
        return False
    words = text.strip().split()
    return 1 <= len(words) <= 4


def read_profile_name(page):
    """Profile display name. Facebook no longer renders the name in
    an h1 (verified live 2026-10-31: zero h1 elements on the profile
    page; the name is a plain DIV) and the tab title is just
    "(N) Facebook", so the name is found by rendered size: the
    largest name-like text near the top of the profile header.
    Title / h1 scans are kept as fallbacks for older markup."""
    try:
        title = (page.title() or "").strip()
        name = re.sub(r"^\(\d+\)\s*", "", title.split("|")[0]).strip()
        if _looks_like_name(name):
            return name
    except Exception:
        pass
    try:
        name = page.evaluate(r"""() => {
            const cands = [];
            for (const e of document.querySelectorAll('div, span, h1, h2')) {
                const t = (e.innerText || '').trim();
                if (!/^[A-Za-z\u00c0-\u00ff'\u2019. -]+$/.test(t)) continue;
                const w = t.split(/\s+/);
                if (w.length < 1 || w.length > 4 || t.length < 2 || t.length > 60) continue;
                const kids = [...e.children].filter(c => (c.innerText || '').trim() === t);
                if (kids.length) continue;
                const fs = parseFloat((getComputedStyle(e).fontSize || '0'));
                const r = e.getBoundingClientRect();
                if (fs < 20 || r.top < 0 || r.top > 600) continue;
                cands.push({t, fs, top: r.top});
            }
            cands.sort((a, b) => b.fs - a.fs || a.top - b.top);
            return cands.length ? cands[0].t : '';
        }""")
        if name and _looks_like_name(name):
            return name
    except Exception:
        pass
    try:
        for el in page.locator("h1").all():
            try:
                text = (el.inner_text(timeout=2000) or "").strip()
            except Exception:
                continue
            if _looks_like_name(text):
                return text
    except Exception:
        pass
    return ""


def _pic_candidates(page):
    return [
        page.locator('img[alt="Profile picture"]').first,
        page.get_by_role("img", name="Profile picture").first,
        page.locator('a[aria-label="Profile picture"] img').first,
        page.locator('div[aria-label="Profile picture"] img').first,
    ]


def _pic_locator(page):
    """First locator that finds the profile picture image, else None."""
    for loc in _pic_candidates(page):
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


def _svg_pic_href(page):
    """Href of the largest visible SVG <image> on the page. Facebook
    renders the header DP circle as an SVG image (168x168, href =
    the scontent photo URL), not an <img> - verified live
    2026-10-31. The nav/composer avatars (40x40) show the same
    photo, so any visible one answers the custom-or-default
    question. None if no SVG image has a usable href."""
    try:
        return page.evaluate("""() => {
            const imgs = [...document.querySelectorAll('svg image')]
                .map(e => ({href: e.getAttribute('href')
                            || e.getAttribute('xlink:href') || '',
                            w: e.getBoundingClientRect().width}))
                .filter(x => x.href && x.w > 0);
            if (!imgs.length) return null;
            imgs.sort((a, b) => b.w - a.w);
            return imgs[0].href;
        }""")
    except Exception:
        return None


def _wait_for_pic(page):
    """Wait until some profile-picture candidate attaches. FB renders
    the header asynchronously; an instant count() misses a picture that
    is still loading. True if found, else False. The header circle is
    an SVG image, so that is waited for too."""
    for loc in _pic_candidates(page):
        try:
            loc.wait_for(state="attached", timeout=5000)
            return True
        except Exception:
            continue
    try:
        page.locator("svg image").first.wait_for(
            state="attached", timeout=5000)
        return True
    except Exception:
        return False


def _pic_src(page):
    """URL of the current profile picture, or None. Tries the <img>
    candidates first, then the SVG image href (the header circle on
    current markup)."""
    loc = _pic_locator(page)
    if loc is not None:
        try:
            src = loc.get_attribute("src", timeout=5000)
            if src:
                return src
        except Exception:
            pass
    return _svg_pic_href(page)


def has_custom_dp(page):
    """True if the profile already has a custom picture, False if the
    picture is a default avatar (i.e. the ID has no DP yet)."""
    src = _pic_src(page)
    if not src:
        return False
    low = src.lower()
    if "scontent" in low:
        return True
    if any(m in low for m in DEFAULT_DP_MARKERS):
        return False
    return True  # unrecognised URL: skip is the safe side


# --- DP upload on one open profile page ---


def _try_click(page, locators):
    """Click the first locator that is present; False if none worked."""
    for loc in locators:
        try:
            if loc.count() > 0 and loc.is_visible():
                _human_click(page, loc)
                return True
        except Exception:
            continue
    return False


def _js_click_by_text(page, exact_text):
    """JS-click the element whose rendered text is exactly exact_text.
    Playwright role clicks time out on this dialog because the dialog
    overlay intercepts them; a JS click does not. Matches on innerText
    (rendered text), NOT textContent: Facebook obfuscates textContent
    with combining characters, so exact textContent matches fail on
    live pages. Prefers a role=menuitem/button match, else the last
    (deepest) match - nested ancestors share the rendered text of the
    clickable leaf. Returns True if an element was clicked, else
    False. LIVE 2026-10-30: the crop dialog is rendered TWICE in the
    DOM (two identical Save buttons at the same coordinates) - the
    first match is the stale duplicate, so the last match must be
    used."""
    try:
        return page.evaluate("""(text) => {
            const els = [...document.querySelectorAll('*')]
                .filter(e => (e.innerText || '').trim() === text);
            if (!els.length) return false;
            const role = els.find(e => ['menuitem', 'button']
                .includes(e.getAttribute('role')));
            (role || els[els.length - 1]).click(); return true;
        }""", exact_text)
    except Exception:
        return False


def _js_click_save(page):
    """Click the crop dialog's Save button. Facebook renders the
    dialog twice in the DOM (two identical role=button Save buttons
    at the same coordinates); the first is a stale duplicate whose
    click does nothing visible, so the LAST match must be clicked.
    Matches on innerText, not textContent (obfuscated on live pages).
    Prefers a div[role=button] with exact text Save, last in DOM."""
    try:
        return page.evaluate("""() => {
            const els = [...document.querySelectorAll('div[role="button"]')]
                .filter(e => (e.innerText || '').trim() === 'Save');
            if (els.length) { els[els.length - 1].click(); return true; }
            const any = [...document.querySelectorAll('*')]
                .filter(e => (e.innerText || '').trim() === 'Save');
            if (any.length) { any[any.length - 1].click(); return true; }
            return false;
        }""")
    except Exception:
        return False


def _js_click_profile_actions(page):
    """JS-click the first element with aria-label
    'Profile picture actions'. Returns True if clicked."""
    try:
        return page.evaluate("""() => {
            const el = [...document.querySelectorAll('[aria-label]')]
                .find(e => e.getAttribute('aria-label')
                           === 'Profile picture actions');
            if (el) { el.click(); return true; }
            return false;
        }""")
    except Exception:
        return False


def _wait_for_text(page, exact_text, timeout_s=10):
    """Poll until an element with the exact rendered text exists.
    The menu/dialog renders slowly on throttled connections - a fixed
    1-2s pause is not enough (live 2026-10-30: the actions menu took
    ~3s to appear after the click). Returns True if found."""
    for _ in range(timeout_s * 2):
        try:
            n = page.evaluate("""(text) => [...document.querySelectorAll('*')]
                .filter(e => (e.innerText || '').trim() === text).length""",
                exact_text)
            if n:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def apply_dp_on_page(page, photo_path):
    """Assumes page is already on the account's own profile, logged in.
    Returns dict(ok, detail). Live-verified flow 2026-10-29,
    CORRECTED 2026-10-30: Profile picture actions -> Choose profile
    picture -> file input index 3 (the profile-picture input; index
    0 is the cover trap and must never be used) -> crop dialog ->
    Save (LAST role=button match - the dialog is rendered twice in
    the DOM). Every step is condition-based; a missing control is an
    honest failure, never a faked success. The before-picture is NOT
    a gate: on some loads the header DP image is not rendered at all
    (no alt="Profile picture" img in the DOM) while the actions
    trigger still exists - so a missing before-src no longer fails
    the run; success is then the "Your profile picture has been
    updated" toast, or a changed picture URL."""
    before = _pic_src(page)
    if not _js_click_profile_actions(page):
        return {"ok": False, "detail": "profile picture actions not found"}
    # The menu renders slowly on throttled connections: poll for it
    # instead of a fixed short pause.
    if not _wait_for_text(page, "Choose profile picture", timeout_s=10):
        return {"ok": False, "detail": "choose profile picture not found"}
    if not _js_click_by_text(page, "Choose profile picture"):
        return {"ok": False, "detail": "choose profile picture not found"}
    _human_pause(1.0, 2.0)
    # Attach the file to input index 3 only. The page holds 4 file
    # inputs in DOM order; index 3 is the image-only profile-picture
    # input. Index 0 sets a cover draft by mistake - never use it,
    # and never fall back to the first input on failure.
    try:
        inputs = page.locator('input[type="file"]')
        # The 4th (profile) input renders with the crop dialog: poll
        # for it instead of an instant count (live 2026-10-30: only 3
        # inputs were present right after the Choose click; live
        # 2026-11-02: the dialog content took ~60s on a throttled
        # connection before the 4th input appeared - so poll 60s.
        # The poll returns the moment the input exists, so a fast
        # connection waits no longer than before.)
        for _ in range(120):
            if inputs.count() >= 4:
                break
            time.sleep(0.5)
        if inputs.count() < 4:
            return {"ok": False,
                    "detail": "profile file input not found "
                              f"(only {inputs.count()} file inputs)"}
        inputs.nth(3).set_input_files(photo_path, timeout=15000)
    except Exception as e:
        return {"ok": False, "detail": f"file attach failed: {e}"}
    # The crop dialog also renders slowly: poll for Save before
    # clicking it.
    if not _wait_for_text(page, "Save", timeout_s=10):
        return {"ok": False, "detail": "save button not found"}
    # Save / confirm in the crop dialog (JS click: role click is
    # intercepted by the dialog overlay, same as Choose above).
    # The dialog is rendered twice: click the LAST Save button.
    if not _js_click_save(page):
        return {"ok": False, "detail": "save button not found"}
    # Verify: the toast proves the save, or the picture URL changes.
    # The crop dialog may stay visible as a stale duplicate after
    # the toast - the toast is the proof, not the dialog closing.
    # Poll up to 15s for either signal.
    for _ in range(15):
        time.sleep(1)
        try:
            body = page.evaluate(
                "() => document.body.innerText.slice(0, 4000)")
        except Exception:
            body = ""
        if "Your profile picture has been updated" in body:
            return {"ok": True, "detail": "profile picture changed"}
        after = _pic_src(page)
        if before and after and after != before:
            return {"ok": True, "detail": "profile picture changed"}
    return {"ok": False, "detail": "picture did not change after save"}


def password_login(page, uid, password):
    """Fill the login form. Returns 'checkpoint', 'submitted', or
    'captcha-unavailable' (a reCAPTCHA gate appeared - the gate is
    left for the user in the visible browser; the caller must
    report that, not a bare 'login failed'). The caller verifies
    the session via the c_user cookie."""
    try:
        page.goto(FB_LOGIN_URL, timeout=30000)
        try:
            _human_type(page, "#email", uid)
            _human_pause(0.5, 1.5)
            _human_type(page, "#pass", password)
        except Exception:
            page.locator('input[name="email"]').fill(uid, timeout=10000)
            page.locator('input[name="pass"]').fill(password, timeout=10000)
        _try_click(page, [
            page.get_by_role("button", name="Log in").first,
            page.get_by_role("button", name="login").first,
            page.locator('button[type="submit"]').first,
        ])
        page.wait_for_timeout(3000)
        if "checkpoint" in page.url.lower():
            return "checkpoint"
        if "two_step" in page.url:
            return "captcha-unavailable"
        return "submitted"
    except Exception:
        return "submitted"


# --- one account, end to end (single login) ---


def _goto_profile(page, url, timeout=30000):
    """Load a profile page without ever raising. Facebook's 'load'
    event can hang on slow assets, so wait only for DOM content and
    retry once. Returns True if the page loaded, else False - the
    caller turns False into a per-account failure, never a crash."""
    for _ in range(2):
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return True
        except Exception:
            continue
    return False


def process_account(pw, account, headless=False):
    """Login -> read name -> skip if DP exists -> else read gender,
    pick a pic from dp_pics/ (name + gender match) and apply it.
    Returns dict(uid, name, ok, skipped, via, detail)."""
    uid = account["uid"]
    from core.browser_launcher import launch_browser
    browser, _ = launch_browser(pw, headless=headless, extra_args=["--no-sandbox"])
    try:
        ctx = browser.new_context()
        cookies = parse_cookie_string(account.get("cookies", ""),
                                      "facebook.com")
        if cookies:
            ctx.add_cookies(cookies)
        page = ctx.new_page()
        if not _goto_profile(page, FB_PROFILE_URL.format(uid=uid)):
            return {"uid": uid, "name": "", "ok": False,
                    "skipped": False, "via": "cookie",
                    "detail": "profile page did not load"}
        _human_pause(1.0, 2.0)
        via = "cookie"
        logged_in = _is_logged_in(page, ctx)
        if not logged_in:
            # Cookie dead (common for old IDs) -> password fallback.
            via = "password"
            status = password_login(page, uid, account["password"])
            if status == "checkpoint":
                return {"uid": uid, "name": "", "ok": False,
                        "skipped": False, "via": via,
                        "detail": "checkpoint - skipped, no retry"}
            if status == "captcha-unavailable":
                return {"uid": uid, "name": "", "ok": False,
                        "skipped": False, "via": via,
                        "detail": "check appeared - "
                                  "solve in browser"}
            if not _goto_profile(page, FB_PROFILE_URL.format(uid=uid)):
                return {"uid": uid, "name": "", "ok": False,
                        "skipped": False, "via": via,
                        "detail": "profile page did not load"}
            _human_pause(1.0, 2.0)
            if not _is_logged_in(page, ctx):
                return {"uid": uid, "name": "", "ok": False,
                        "skipped": False, "via": via,
                        "detail": "login failed"}
        name = read_profile_name(page)
        # The header DP image is not a gate: on some loads it is
        # never rendered (no alt="Profile picture" img in the DOM)
        # while the actions trigger still exists. Retry once after a
        # reload; if it is still missing, proceed anyway - the
        # skip check below only runs when a picture is present, and
        # apply_dp_on_page verifies by toast or URL change.
        if not _wait_for_pic(page):
            if _goto_profile(page, FB_PROFILE_URL.format(uid=uid)):
                _human_pause(1.0, 2.0)
                _wait_for_pic(page)
        if has_custom_dp(page):
            return {"uid": uid, "name": name, "ok": True, "skipped": True,
                    "via": via, "detail": "already has DP - skipped"}
        gender, method = detect_gender(page, uid, name)
        # Gender read moves the page to About - go back to the
        # profile before the upload (apply_dp_on_page needs the
        # profile page).
        if not _goto_profile(page, FB_PROFILE_URL.format(uid=uid)):
            return {"uid": uid, "name": "", "ok": False,
                    "skipped": False, "via": via,
                    "detail": "profile page did not load"}
        _human_pause(1.0, 2.0)
        picked = pick_dp(name, gender)
        if not picked and gender:
            gen_path = _dp_generate_pic(gender)
            if gen_path:
                picked = {"path": gen_path, "gender": gender,
                          "reason": "generated"}
        if not picked:
            if gender:
                detail = (f"no DP pic for {gender} - add photos to "
                          f"dp_pics/{gender}/")
            else:
                detail = (f"gender unknown and no pic named for "
                          f"'{name}' - add a pic named '{name}' to "
                          "dp_pics/male/ or dp_pics/female/")
            return {"uid": uid, "name": name, "ok": False,
                    "skipped": False, "via": via, "detail": detail}
        res = apply_dp_on_page(page, picked["path"])
        if res["ok"]:
            record_used(used_file_path(), picked["path"])
            res["detail"] = ("profile picture changed "
                             f"({os.path.basename(picked['path'])}, "
                             f"{picked['gender'] or 'gender unknown'}, "
                             f"{picked['reason']}, gender via {method})")
        res["uid"] = uid
        res["name"] = name
        res["via"] = via
        res["skipped"] = False
        return res
    finally:
        browser.close()


# --- interactive entry (main.py mode 5) ---


def run_dp_mode():
    print(f"{CYAN}=== DP Apply (test version) ==={WHITE}")
    print(f"{CYAN}DP pics folder: {dp_pics_dir()}{WHITE}")
    status = folder_status()
    print(f"{CYAN}male: {status['male']} pic(s), "
          f"female: {status['female']} pic(s){WHITE}")
    if status["male"] + status["female"] == 0:
        print(f"{YELLOW}No DP pics found - put photos in dp_pics/male/ "
              f"or dp_pics/female/ (see dp_pics/README.md).{WHITE}")
    accounts = parse_accounts_file(
        os.path.join(get_output_dir(), "browser_accounts.txt"))
    if not accounts:
        print(f"{RED}No accounts in output/browser_accounts.txt{WHITE}")
        return
    print(f"{CYAN}Found {len(accounts)} account(s). "
          f"Only IDs without a DP will get one.{WHITE}")
    try:
        gap = int(input(
            f"{CYAN}Gap between accounts in seconds [60] {WHITE}"
        ).strip() or "60")
    except Exception:
        gap = 60
    gap = max(0, min(gap, 300))
    applied = skipped = failed = 0
    with sync_playwright() as pw:
        for i, account in enumerate(accounts):
            if i > 0:
                time.sleep(gap)
            try:
                res = process_account(pw, account, headless=False)
            except Exception as e:
                # One account's unexpected failure must never kill
                # the batch: record it and move to the next account.
                res = {"uid": account["uid"], "name": "",
                       "ok": False, "skipped": False, "via": "",
                       "detail": f"unexpected error: {e}"}
            label = res.get("name") or res["uid"]
            if res.get("skipped"):
                skipped += 1
                print(f"{YELLOW}[DP] {label}: skipped - {res['detail']}"
                      f"{WHITE}")
            elif res["ok"]:
                applied += 1
                print(f"{GREEN}[DP] {label}: applied via {res['via']}"
                      f"{WHITE}")
            else:
                failed += 1
                print(f"{RED}[DP] {label}: FAILED - {res['detail']}"
                      f"{WHITE}")
    print(f"{CYAN}Done: applied {applied}, skipped {skipped}, "
          f"failed {failed}.{WHITE}")
