"""
AI Video Clipper - Main Application
====================================
A web tool that downloads online videos or takes uploaded videos,
transcribes them with Whisper/captions, uses Gemini AI to suggest
viral clip moments, and renders high-quality clips in 9:16 vertical ratio.
Supports multi-hour videos, configurable clip quantities (e.g. 5, 8, 10, 15),
fast download options, and batch ZIP downloads.
"""

import os
import sys
import json
import uuid
import time
import subprocess
import threading
import re
import io
import html
import zipfile
from pathlib import Path
from datetime import timedelta

from flask import (
    Flask, render_template, request, jsonify,
    send_file, send_from_directory, url_for
)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# 16 GB max upload limit for large multi-hour local video files
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 * 1024

# --- Configuration ---
BASE_DIR = Path(__file__).parent.resolve()
DOWNLOADS_DIR = BASE_DIR / "downloads"
CLIPS_DIR = BASE_DIR / "clips"
DOWNLOADS_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base").strip()
# 0 = No duration limit (supports videos of duration in hours)
MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", 0))
CLIP_FORMAT = os.getenv("CLIP_FORMAT", "mp4").strip()
DEFAULT_ASPECT_RATIO = os.getenv("DEFAULT_ASPECT_RATIO", "9:16_blur").strip()
DEFAULT_NUM_CLIPS = int(os.getenv("DEFAULT_NUM_CLIPS", 8))

# In-memory job store
jobs = {}


# ===================== ERROR HANDLERS =====================

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle large file upload error with JSON instead of HTML."""
    return jsonify({
        "error": "The uploaded video exceeds the 16GB limit. Please upload files under 16GB."
    }), 413


# ===================== UTILITIES =====================

def format_timestamp(seconds):
    """Convert seconds to HH:MM:SS format."""
    seconds = max(0, float(seconds))
    td = timedelta(seconds=int(seconds))
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_timestamp(ts_str):
    """Convert HH:MM:SS or MM:SS to seconds."""
    if isinstance(ts_str, (int, float)):
        return float(ts_str)
    parts = str(ts_str).strip().replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    else:
        return float(parts[0])


def get_ffmpeg_path():
    """Find ffmpeg binary reliably on Windows and other OS."""
    # 1. Check imageio_ffmpeg
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    # 2. Check if ffmpeg is in PATH
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 3. Check common Windows locations
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    return "ffmpeg"


FFMPEG_PATH = get_ffmpeg_path()


def clean_subtitle_text(raw_text):
    """
    Cleans raw subtitle text:
    - Decodes HTML entities (&gt;&gt;, &amp;, &quot;, &#39;, etc.)
    - Strips speaker tags and sound annotations [Music], (Laughter), >>, >>>
    - Strips formatting tags (<c>, <b>, <00:01:23.456>)
    - Collapses whitespace
    """
    if not raw_text:
        return ""

    # Decode HTML entities twice (to catch &amp;gt; or &gt;&gt;)
    text = html.unescape(raw_text)
    text = html.unescape(text)

    # Strip timestamps and HTML/VTT tags
    text = re.sub(r'<[^>]+>', '', text)

    # Strip sound annotations e.g. [Music], [Applause], (cheering), (groans)
    text = re.sub(r'\[[^\]]*\]', '', text)
    text = re.sub(r'\([^\)]*\)', '', text)

    # Strip speaker change markers e.g. >>, >>>, -, --
    text = re.sub(r'^(?:>{1,4}|-{1,4})\s*', '', text)
    text = re.sub(r'\s+(?:>{1,4}|-{1,4})\s+', ' ', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_vtt(content):
    """Parse WebVTT subtitle text into timestamped segments with deduplication."""
    pattern = re.compile(
        r'(\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})[^\n]*\n([\s\S]*?)(?=\n\s*\n|\Z)'
    )
    segments = []

    def to_secs(ts):
        ts = ts.replace(',', '.')
        parts = ts.split(':')
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return float(parts[0]) * 60 + float(parts[1])

    last_text = ""
    for i, m in enumerate(pattern.finditer(content)):
        start, end, raw_text = m.groups()
        clean_text = clean_subtitle_text(raw_text)

        # Skip empty or duplicate consecutive lines
        if not clean_text or clean_text == last_text:
            continue

        s_sec = round(to_secs(start), 2)
        e_sec = round(to_secs(end), 2)

        if e_sec > s_sec:
            segments.append({
                "id": len(segments),
                "start": s_sec,
                "end": e_sec,
                "start_str": format_timestamp(s_sec),
                "end_str": format_timestamp(e_sec),
                "text": clean_text
            })
            last_text = clean_text

    return segments


# ===================== VIDEO METADATA & INFO =====================

def get_video_info(url):
    """Get video metadata without downloading the full video."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--dump-json",
        "--no-download",
        "--no-warnings",
        url
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            duration = float(info.get("duration") or 0)
            return {
                "title": info.get("title", "Unknown Title"),
                "duration": duration,
                "duration_str": format_timestamp(duration),
                "thumbnail": info.get("thumbnail", ""),
                "uploader": info.get("uploader", "Unknown"),
                "view_count": info.get("view_count", 0),
                "description": (info.get("description", "") or "")[:500],
            }
    except Exception as e:
        print(f"get_video_info error: {e}")
    return None


def fetch_video_subtitles(url, job_id):
    """Try to extract subtitles from video without downloading video stream."""
    sub_prefix = str(DOWNLOADS_DIR / f"{job_id}_sub")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-lang", "en,en-US,en-GB,en-orig,en-AU,en-CA,en-IN,hi,es,auto",
        "--sub-format", "vtt/srt/best",
        "-o", f"{sub_prefix}.%(ext)s",
        "--no-warnings",
        url
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        for f in DOWNLOADS_DIR.iterdir():
            if f.stem.startswith(f"{job_id}_sub") and f.suffix.lower() in [".vtt", ".srt"]:
                content = f.read_text(encoding="utf-8", errors="ignore")
                segments = parse_vtt(content)
                if segments:
                    return segments
    except Exception:
        pass
    return None


# ===================== TRANSCRIPTION & MOMENTS GENERATOR =====================

def generate_multi_hour_suggestions(duration, transcript=None, num_clips=8):
    """
    Generate the user's requested number of strategic viral clip moments across any video timeline.
    Works for videos from 1 minute up to 10+ hours.
    """
    duration = float(duration or 0)
    suggestions = []
    num_clips = max(1, min(int(num_clips or 8), 25))

    if duration <= 10:
        return []

    titles_pool = [
        ("Opening Hook", "First 30 seconds hook to instantly grab attention", 9),
        ("Early Action Scene", "Early key gameplay / discussion moment", 8),
        ("Topic Introduction", "Setting up the main conflict or topic", 8),
        ("Rising Excitement", "Building tension and engaging discussion", 8),
        ("Mid-Video Turning Point", "Central intense highlight / plot twist", 9),
        ("Peak Engagement Moment", "High-energy action and reactions", 9),
        ("Major Story Development", "Surprising reveal or key milestone", 8),
        ("Intense Showdown", "High-stakes segment with rapid engagement", 9),
        ("Dramatic Twist", "Unexpected turn of events / memorable quote", 8),
        ("Climactic Peak", "The biggest moment before the ending", 9),
        ("Final Climax", "High-energy conclusion to the main event", 8),
        ("Ending Takeaway", "Punchy closing scene for viral loop", 8),
    ]

    # If transcript is available and has enough segments
    if transcript and len(transcript) >= num_clips:
        total_segs = len(transcript)
        step = total_segs / num_clips
        for i in range(num_clips):
            seg_idx = min(int(i * step), total_segs - 1)
            start_sec = transcript[seg_idx]["start"]
            target_dur = 35.0
            end_sec = min(start_sec + target_dur, duration if duration > 0 else start_sec + target_dur)

            t_idx = int((i / max(1, num_clips - 1)) * (len(titles_pool) - 1))
            t_info = titles_pool[t_idx]
            title = f"Moment #{i+1}: {t_info[0]}" if num_clips > 5 else t_info[0]

            if end_sec > start_sec + 5:
                suggestions.append({
                    "title": title,
                    "start": format_timestamp(start_sec),
                    "end": format_timestamp(end_sec),
                    "start_seconds": round(start_sec, 2),
                    "end_seconds": round(end_sec, 2),
                    "reason": t_info[1],
                    "score": t_info[2]
                })
        return suggestions

    # Timeline-based distribution across duration
    usable_start = min(15.0, duration * 0.02)
    usable_end = max(usable_start + 30.0, duration * 0.98)
    total_range = max(10.0, usable_end - usable_start)

    step = total_range / num_clips
    clip_len = min(45.0, max(20.0, step * 0.75))

    for i in range(num_clips):
        start_s = round(usable_start + (i * step), 2)
        end_s = round(min(start_s + clip_len, duration), 2)

        t_idx = int((i / max(1, num_clips - 1)) * (len(titles_pool) - 1))
        t_info = titles_pool[t_idx]
        title = f"Moment #{i+1}: {t_info[0]}" if num_clips > 5 else t_info[0]

        if end_s > start_s + 5:
            suggestions.append({
                "title": title,
                "start": format_timestamp(start_s),
                "end": format_timestamp(end_s),
                "start_seconds": start_s,
                "end_seconds": end_s,
                "reason": t_info[1],
                "score": t_info[2]
            })

    return suggestions


def suggest_clips_with_ai(job_id, num_clips=8):
    """Use Groq (Llama 3.3 70B), Gemini AI, or timeline generator to produce requested number of viral 9:16 clip moments."""
    job = jobs[job_id]
    job["status"] = "analyzing"
    job["message"] = f"Analyzing timeline for top {num_clips} viral 9:16 moments..."

    transcript = job.get("transcript", [])
    duration = job.get("duration", 0)
    num_clips = max(1, min(int(num_clips or DEFAULT_NUM_CLIPS), 25))

    has_groq = bool(GROQ_API_KEY and GROQ_API_KEY not in ["your_groq_api_key_here"])
    has_gemini = bool(GEMINI_API_KEY and GEMINI_API_KEY not in ["your_gemini_api_key_here", "your_actual_key_here"])

    # If no AI keys configured, use strategic timeline distribution
    if not has_groq and not has_gemini:
        suggestions = generate_multi_hour_suggestions(duration, transcript, num_clips=num_clips)
        job["suggestions"] = suggestions
        job["message"] = f"Generated {len(suggestions)} suggested 9:16 clip moments across the timeline!"
        job["status"] = "ready"
        return suggestions

    # If we have transcript and an AI key
    if transcript and len(transcript) > 0:
        transcript_text = ""
        for seg in transcript[:250]:
            transcript_text += f"[{seg['start_str']}] {seg['text']}\n"

        prompt = f"""You are a professional viral video editor specializing in 9:16 vertical shorts, Reels, and TikToks.
Analyze this video transcript and identify exactly {num_clips} of the most viral, captivating, or insightful clips.

Video Duration: {format_timestamp(duration)}

TRANSCRIPT:
{transcript_text[:10000]}

INSTRUCTIONS:
1. Identify exactly {num_clips} of the absolute best moments (hooks, punchlines, dramatic statements, intense gameplay, tips).
2. Each clip must be 15 to 90 seconds long.
3. For each clip provide:
   - "title": Catchy, viral title
   - "start": Start timestamp (HH:MM:SS)
   - "end": End timestamp (HH:MM:SS)
   - "reason": Why this makes a viral 9:16 vertical clip
   - "score": Virality score from 1 to 10

Return ONLY valid JSON in this exact structure:
{{
  "clips": [
    {{
      "title": "Clip Title Here",
      "start": "00:01:30",
      "end": "00:02:15",
      "reason": "Why this is interesting",
      "score": 9
    }}
  ]
}}"""

        # 1. Try Groq Llama 3.3 70B Versatile first if key available
        if has_groq:
            try:
                from groq import Groq
                client = Groq(api_key=GROQ_API_KEY)
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are a professional viral short-form video editor. You respond only in valid JSON format."},
                        {"role": "user", "content": prompt}
                    ],
                    model="llama-3.3-70b-versatile",
                    response_format={"type": "json_object"},
                    temperature=0.3
                )
                raw_res = chat_completion.choices[0].message.content
                data = json.loads(raw_res)
                clips = data.get("clips", [])
                valid_clips = []
                for clip in clips:
                    try:
                        s_sec = parse_timestamp(clip["start"])
                        e_sec = parse_timestamp(clip["end"])
                        if e_sec > s_sec:
                            clip["start_seconds"] = round(s_sec, 2)
                            clip["end_seconds"] = round(e_sec, 2)
                            valid_clips.append(clip)
                    except Exception:
                        continue

                valid_clips.sort(key=lambda x: x.get("score", 0), reverse=True)
                if valid_clips:
                    job["suggestions"] = valid_clips
                    job["message"] = f"Groq Llama 3.3 identified {len(valid_clips)} high-virality 9:16 moments!"
                    job["status"] = "ready"
                    return valid_clips
            except Exception as e:
                print(f"Groq API call error: {e}")

        # 2. Try Gemini AI if available
        if has_gemini:
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)

                model_name = "gemini-2.0-flash"
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                except Exception:
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    response = model.generate_content(prompt)

                json_match = re.search(r'\{[\s\S]*\}', response.text)
                if json_match:
                    data = json.loads(json_match.group())
                    clips = data.get("clips", [])
                    valid_clips = []
                    for clip in clips:
                        try:
                            s_sec = parse_timestamp(clip["start"])
                            e_sec = parse_timestamp(clip["end"])
                            if e_sec > s_sec:
                                clip["start_seconds"] = round(s_sec, 2)
                                clip["end_seconds"] = round(e_sec, 2)
                                valid_clips.append(clip)
                        except Exception:
                            continue

                    valid_clips.sort(key=lambda x: x.get("score", 0), reverse=True)
                    if valid_clips:
                        job["suggestions"] = valid_clips
                        job["message"] = f"Gemini discovered {len(valid_clips)} high-virality 9:16 moments!"
                        job["status"] = "ready"
                        return valid_clips
            except Exception as e:
                print(f"Gemini call error: {e}")

    # Fallback to strategic timeline distribution
    suggestions = generate_multi_hour_suggestions(duration, transcript, num_clips=num_clips)
    job["suggestions"] = suggestions
    job["message"] = f"Generated {len(suggestions)} strategic 9:16 clip moments!"
    job["status"] = "ready"
    return suggestions


# ===================== CLIPPING ENGINE (9:16, SUBTITLES & HIGH SPEED / QUALITY) =====================

def render_ffmpeg_9_16(input_video_path, output_clip_path, start_seconds, duration,
                       aspect_ratio="9:16_blur", quality="fast", is_already_trimmed=False,
                       subtitles_srt_path=None):
    """
    Renders input video into 9:16 vertical video with optional burnt-in viral subtitles.
    Supports:
    - 'fast': Ultrafast render (~1s), CRF 23, 720x1280 9:16, for fast preview & quick download
    - 'high': High Quality, CRF 18, 1080x1920 Full HD 9:16
    """
    if quality == "fast":
        crf = "23"
        preset = "ultrafast"
        audio_bitrate = "128k"
        width = 720
        height = 1280
        bg_w = 240
        bg_h = 426
        # Instagram Reel medium aesthetic typography (720x1280)
        sub_font_size = "13"
        sub_margin_v = "55"
        sub_outline = "1.8"
    else:
        crf = "18"
        preset = "fast"
        audio_bitrate = "192k"
        width = 1080
        height = 1920
        bg_w = 360
        bg_h = 640
        # Instagram Reel medium aesthetic typography (1080x1920)
        sub_font_size = "19"
        sub_margin_v = "80"
        sub_outline = "2.2"

    cmd = [FFMPEG_PATH]

    abs_input = str(Path(input_video_path).resolve())

    if not is_already_trimmed:
        cmd.extend([
            "-ss", str(start_seconds),
            "-i", abs_input,
            "-t", str(duration),
        ])
    else:
        cmd.extend([
            "-i", abs_input
        ])

    # Subtitle filter string (Instagram Reel style: medium size, clean bold font, crisp outline)
    sub_filter = ""
    run_cwd = os.getcwd()
    if subtitles_srt_path and os.path.exists(subtitles_srt_path):
        run_cwd = str(Path(subtitles_srt_path).parent.resolve())
        rel_srt = Path(subtitles_srt_path).name
        sub_filter = (
            f"subtitles={rel_srt}:force_style='Fontname=Arial,Bold=1,"
            f"Fontsize={sub_font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"BackColour=&H66000000,BorderStyle=1,Outline={sub_outline},Shadow=1,"
            f"Alignment=2,MarginV={sub_margin_v},MarginL=30,MarginR=30'"
        )

    # Configure aspect ratio filters
    if aspect_ratio == "9:16_blur":
        # Ultra-fast bokeh blur background (scaled down, blurred, upscaled for 40x speedup)
        if sub_filter:
            filter_complex = (
                f"[0:v]scale={bg_w}:{bg_h}:force_original_aspect_ratio=increase,"
                f"crop={bg_w}:{bg_h},boxblur=6:1,"
                f"scale={width}:{height}:flags=fast_bilinear[bg];"
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{sub_filter}"
            )
        else:
            filter_complex = (
                f"[0:v]scale={bg_w}:{bg_h}:force_original_aspect_ratio=increase,"
                f"crop={bg_w}:{bg_h},boxblur=6:1,"
                f"scale={width}:{height}:flags=fast_bilinear[bg];"
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
            )
        cmd.extend(["-filter_complex", filter_complex])
    elif aspect_ratio == "9:16_crop":
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        if sub_filter:
            vf += f",{sub_filter}"
        cmd.extend(["-vf", vf])
    elif aspect_ratio == "9:16_fit":
        vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        if sub_filter:
            vf += f",{sub_filter}"
        cmd.extend(["-vf", vf])
    else:
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        if sub_filter:
            vf += f",{sub_filter}"
        cmd.extend(["-vf", vf])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", crf,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-threads", "0",
        "-movflags", "+faststart",
        "-y",
        str(Path(output_clip_path).resolve())
    ])

    result = subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, timeout=300)
    return result


def wrap_text_reels(text, max_chars=34):
    """Clean subtitle text and wrap into max 2 lines for Instagram Reel style."""
    text = clean_subtitle_text(text)
    words = text.split()
    if not words:
        return ""
    lines = []
    cur_line = []
    cur_len = 0
    for w in words:
        if cur_len + len(w) + (1 if cur_line else 0) > max_chars:
            if cur_line:
                lines.append(" ".join(cur_line))
            cur_line = [w]
            cur_len = len(w)
        else:
            cur_line.append(w)
            cur_len += len(w) + (1 if len(cur_line) > 1 else 0)
    if cur_line:
        lines.append(" ".join(cur_line))
    # Keep to max 2 lines at once on screen
    return "\\N".join(lines[:2])


def generate_clip_srt_file(job_id, start_seconds, end_seconds, temp_srt_path):
    """
    Extracts relevant transcript lines for the clip's timestamp window,
    formats them into crisp, medium-sized Instagram Reel style subtitles,
    and normalizes timestamps relative to clip start (00:00:00).
    """
    job = jobs.get(job_id, {})
    transcript = job.get("transcript", [])
    if not transcript:
        return False

    clip_subs = []
    last_text = ""
    for seg in transcript:
        s = seg.get("start", 0)
        e = seg.get("end", 0)
        raw_text = seg.get("text", "").strip()
        text = clean_subtitle_text(raw_text)

        # Overlaps with clip window
        if e > start_seconds and s < end_seconds and text:
            # Shift timestamps relative to clip beginning
            rel_s = max(0.0, s - start_seconds)
            rel_e = min(end_seconds - start_seconds, e - start_seconds)
            if rel_e > rel_s + 0.2:
                formatted_text = wrap_text_reels(text, max_chars=34)
                if formatted_text and formatted_text != last_text:
                    clip_subs.append((rel_s, rel_e, formatted_text))
                    last_text = formatted_text

    if not clip_subs:
        return False

    def srt_ts(seconds):
        sec = max(0.0, float(seconds))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for idx, (s, e, text) in enumerate(clip_subs, start=1):
        lines.append(f"{idx}\n{srt_ts(s)} --> {srt_ts(e)}\n{text}\n")

    Path(temp_srt_path).write_text("\n".join(lines), encoding="utf-8")
    return True


def create_clip_from_url(url, start_seconds, end_seconds, clip_name, job_id,
                         aspect_ratio="9:16_blur", quality="fast", with_subtitles=False):
    """
    Directly extracts and downloads the requested timestamp section from an online URL
    using yt-dlp's --download-sections, then renders into 9:16 MP4 with optional subtitles.
    Works for videos of ANY length in just a few seconds!
    """
    clean_name = re.sub(r'[^\w\-_\. ]', '_', clip_name.strip())[:40] or "clip"
    unique_suffix = uuid.uuid4().hex[:6]
    clip_filename = f"{job_id}_{clean_name}_{unique_suffix}.{CLIP_FORMAT}"
    clip_path = CLIPS_DIR / clip_filename
    temp_section = DOWNLOADS_DIR / f"temp_{job_id}_{unique_suffix}.mp4"
    temp_srt = DOWNLOADS_DIR / f"temp_{job_id}_{unique_suffix}.srt"

    duration = max(0.5, end_seconds - start_seconds)

    # 1. Download just the specific section from YouTube / online site
    start_ts = format_timestamp(start_seconds)
    end_ts = format_timestamp(end_seconds)

    format_choice = "bestvideo[height<=720]+bestaudio/best[height<=720]/best" if quality == "fast" else "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"

    cmd_dl = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", FFMPEG_PATH,
        "--download-sections", f"*{start_ts}-{end_ts}",
        "-f", format_choice,
        "--merge-output-format", "mp4",
        "-o", str(temp_section),
        "--no-warnings",
        "--concurrent-fragments", "4",
        url
    ]

    try:
        res_dl = subprocess.run(cmd_dl, capture_output=True, text=True, timeout=180)
        if res_dl.returncode != 0 or not temp_section.exists():
            return {
                "success": False,
                "error": f"Failed to download clip section: {res_dl.stderr[:300]}"
            }

        srt_file = None
        if with_subtitles:
            has_subs = generate_clip_srt_file(job_id, start_seconds, end_seconds, temp_srt)
            if has_subs:
                srt_file = temp_srt

        # 2. Render the downloaded section into 9:16
        res_ff = render_ffmpeg_9_16(
            input_video_path=temp_section,
            output_clip_path=clip_path,
            start_seconds=0,
            duration=duration,
            aspect_ratio=aspect_ratio,
            quality=quality,
            is_already_trimmed=True,
            subtitles_srt_path=srt_file
        )

        # Cleanup temporary files
        for p in [temp_section, temp_srt]:
            if p.exists():
                try:
                    os.remove(p)
                except Exception:
                    pass

        if res_ff.returncode == 0 and clip_path.exists():
            size_mb = round(clip_path.stat().st_size / (1024 * 1024), 2)
            ratio_label = {
                "9:16_blur": "9:16 Vertical (Blur Background)",
                "9:16_crop": "9:16 Vertical (Fill / Crop)",
                "9:16_fit": "9:16 Vertical (Fit / Black Bars)",
                "original": "Original Ratio"
            }.get(aspect_ratio, "9:16 Vertical")

            quality_label = "720x1280 (Fast)" if quality == "fast" else "1080x1920 (Full HD)"
            sub_label = " • 💬 Subtitles" if (with_subtitles and srt_file) else ""

            return {
                "success": True,
                "filename": clip_filename,
                "title": clip_name,
                "path": str(clip_path),
                "size_mb": size_mb,
                "duration": round(duration, 2),
                "duration_str": format_timestamp(duration),
                "aspect_ratio": aspect_ratio,
                "ratio_label": ratio_label + sub_label,
                "quality": quality_label,
                "has_subtitles": bool(with_subtitles and srt_file),
                "download_url": f"/api/download-clip/{clip_filename}?name={clean_name}_9x16",
                "preview_url": f"/clips/{clip_filename}",
            }
        else:
            return {"success": False, "error": f"FFmpeg render error: {res_ff.stderr[-300:]}"}

    except Exception as e:
        for p in [temp_section, temp_srt]:
            if p.exists():
                try:
                    os.remove(p)
                except Exception:
                    pass
        return {"success": False, "error": str(e)}


def create_clip_from_local(video_path, start_seconds, end_seconds, clip_name, job_id,
                           aspect_ratio="9:16_blur", quality="fast", with_subtitles=False):
    """Render 9:16 clip directly from a local uploaded video file with optional subtitles."""
    clean_name = re.sub(r'[^\w\-_\. ]', '_', clip_name.strip())[:40] or "clip"
    unique_suffix = uuid.uuid4().hex[:6]
    clip_filename = f"{job_id}_{clean_name}_{unique_suffix}.{CLIP_FORMAT}"
    clip_path = CLIPS_DIR / clip_filename
    temp_srt = DOWNLOADS_DIR / f"temp_{job_id}_{unique_suffix}.srt"

    duration = max(0.5, end_seconds - start_seconds)

    try:
        srt_file = None
        if with_subtitles:
            has_subs = generate_clip_srt_file(job_id, start_seconds, end_seconds, temp_srt)
            if has_subs:
                srt_file = temp_srt

        res_ff = render_ffmpeg_9_16(
            input_video_path=video_path,
            output_clip_path=clip_path,
            start_seconds=start_seconds,
            duration=duration,
            aspect_ratio=aspect_ratio,
            quality=quality,
            is_already_trimmed=False,
            subtitles_srt_path=srt_file
        )

        if temp_srt.exists():
            try:
                os.remove(temp_srt)
            except Exception:
                pass

        if res_ff.returncode == 0 and clip_path.exists():
            size_mb = round(clip_path.stat().st_size / (1024 * 1024), 2)
            ratio_label = {
                "9:16_blur": "9:16 Vertical (Blur Background)",
                "9:16_crop": "9:16 Vertical (Fill / Crop)",
                "9:16_fit": "9:16 Vertical (Fit / Black Bars)",
                "original": "Original Ratio"
            }.get(aspect_ratio, "9:16 Vertical")

            quality_label = "720x1280 (Fast)" if quality == "fast" else "1080x1920 (Full HD)"
            sub_label = " • 💬 Subtitles" if (with_subtitles and srt_file) else ""

            return {
                "success": True,
                "filename": clip_filename,
                "title": clip_name,
                "path": str(clip_path),
                "size_mb": size_mb,
                "duration": round(duration, 2),
                "duration_str": format_timestamp(duration),
                "aspect_ratio": aspect_ratio,
                "ratio_label": ratio_label + sub_label,
                "quality": quality_label,
                "has_subtitles": bool(with_subtitles and srt_file),
                "download_url": f"/api/download-clip/{clip_filename}?name={clean_name}_9x16",
                "preview_url": f"/clips/{clip_filename}",
            }
        else:
            return {"success": False, "error": f"FFmpeg render error: {res_ff.stderr[-300:]}"}

    except Exception as e:
        if temp_srt.exists():
            try:
                os.remove(temp_srt)
            except Exception:
                pass
        return {"success": False, "error": str(e)}
    clip_filename = f"{job_id}_{clean_name}_{unique_suffix}.{CLIP_FORMAT}"
    clip_path = CLIPS_DIR / clip_filename

    duration = max(0.5, end_seconds - start_seconds)

    try:
        res_ff = render_ffmpeg_9_16(
            input_video_path=video_path,
            output_clip_path=clip_path,
            start_seconds=start_seconds,
            duration=duration,
            aspect_ratio=aspect_ratio,
            quality=quality,
            is_already_trimmed=False
        )

        if res_ff.returncode == 0 and clip_path.exists():
            size_mb = round(clip_path.stat().st_size / (1024 * 1024), 2)
            ratio_label = {
                "9:16_blur": "9:16 Vertical (Blur Background)",
                "9:16_crop": "9:16 Vertical (Fill / Crop)",
                "9:16_fit": "9:16 Vertical (Fit / Black Bars)",
                "original": "Original Ratio"
            }.get(aspect_ratio, "9:16 Vertical")

            quality_label = "720x1280 (Fast)" if quality == "fast" else "1080x1920 (Full HD)"

            return {
                "success": True,
                "filename": clip_filename,
                "title": clip_name,
                "path": str(clip_path),
                "size_mb": size_mb,
                "duration": round(duration, 2),
                "duration_str": format_timestamp(duration),
                "aspect_ratio": aspect_ratio,
                "ratio_label": ratio_label,
                "quality": quality_label,
                "download_url": f"/api/download-clip/{clip_filename}?name={clean_name}_9x16",
                "preview_url": f"/clips/{clip_filename}",
            }
        else:
            return {"success": False, "error": f"FFmpeg render error: {res_ff.stderr[-300:]}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ===================== BACKGROUND PIPELINE =====================

def process_video_pipeline(url, job_id, is_local_upload=False, local_filepath=None, num_clips=8):
    """
    High-performance pipeline:
    - For URLs: fetches metadata in 2 seconds; prepares requested number of clips.
    - For Local Uploads: probes duration and sets up moments.
    - Works instantly for multi-hour videos!
    """
    job = jobs[job_id]

    if is_local_upload and local_filepath:
        video_path = local_filepath
        job["video_path"] = video_path
        job["status"] = "processing"
        job["message"] = "Local video loaded. Inspecting timeline..."

        try:
            cmd = [FFMPEG_PATH, "-i", video_path, "-hide_banner"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.?\d*)', result.stderr)
            if duration_match:
                h, m, s = duration_match.groups()
                job["duration"] = int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            job["duration"] = 0

        # Try Whisper transcription if video <= 20 mins
        if job["duration"] <= 1200:
            try:
                import whisper
                job["status"] = "transcribing"
                job["message"] = "Transcribing with Whisper AI..."
                model = whisper.load_model(WHISPER_MODEL)
                result = model.transcribe(video_path, verbose=False, word_timestamps=False)
                segments = []
                for seg in result.get("segments", []):
                    s_sec = round(float(seg["start"]), 2)
                    e_sec = round(float(seg["end"]), 2)
                    segments.append({
                        "id": seg["id"],
                        "start": s_sec,
                        "end": e_sec,
                        "start_str": format_timestamp(s_sec),
                        "end_str": format_timestamp(e_sec),
                        "text": seg["text"].strip(),
                    })
                job["transcript"] = segments
            except Exception:
                job["transcript"] = []
        else:
            job["transcript"] = []

        suggest_clips_with_ai(job_id, num_clips=num_clips)
        job["status"] = "ready"
        job["message"] = f"Ready! {len(job.get('suggestions', []))} moments prepared from {format_timestamp(job['duration'])} video."

    else:
        # URL Pipeline
        job["status"] = "downloading"
        job["message"] = "Fetching video details & timeline..."

        info = get_video_info(url)
        if not info:
            job["status"] = "error"
            job["message"] = "Could not fetch video info from URL. Please check the link."
            return

        job["title"] = info.get("title", "Video")
        job["duration"] = info.get("duration", 0)

        # Try to fetch captions without rate-limiting
        job["status"] = "transcribing"
        job["message"] = "Loading captions & timeline markers..."
        captions = fetch_video_subtitles(url, job_id)
        if captions:
            job["transcript"] = captions
        else:
            job["transcript"] = []

        # Generate moments across the entire video
        suggest_clips_with_ai(job_id, num_clips=num_clips)

        job["status"] = "ready"
        job["message"] = f"Ready! {len(job.get('suggestions', []))} viral 9:16 moments prepared. Choose any moment for instant download!"


# ===================== ROUTES =====================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or update app configuration."""
    global GEMINI_API_KEY, GROQ_API_KEY
    if request.method == "POST":
        data = request.get_json() or {}
        new_gemini = data.get("gemini_api_key", "").strip()
        new_groq = data.get("groq_api_key", "").strip()

        env_path = BASE_DIR / ".env"
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")

        if new_gemini:
            GEMINI_API_KEY = new_gemini
            if "GEMINI_API_KEY=" in content:
                content = re.sub(r'GEMINI_API_KEY=.*', f'GEMINI_API_KEY={new_gemini}', content)
            else:
                content += f"\nGEMINI_API_KEY={new_gemini}\n"

        if new_groq:
            GROQ_API_KEY = new_groq
            if "GROQ_API_KEY=" in content:
                content = re.sub(r'GROQ_API_KEY=.*', f'GROQ_API_KEY={new_groq}', content)
            else:
                content += f"\nGROQ_API_KEY={new_groq}\n"

        env_path.write_text(content, encoding="utf-8")
        return jsonify({"success": True, "message": "API Keys updated!"})

    has_gemini = bool(GEMINI_API_KEY and GEMINI_API_KEY not in ["your_gemini_api_key_here", "your_actual_key_here"])
    has_groq = bool(GROQ_API_KEY and GROQ_API_KEY not in ["your_groq_api_key_here"])

    return jsonify({
        "gemini_configured": has_gemini,
        "groq_configured": has_groq,
        "whisper_model": WHISPER_MODEL,
        "ffmpeg_path": FFMPEG_PATH,
        "default_aspect_ratio": DEFAULT_ASPECT_RATIO,
        "clip_format": CLIP_FORMAT,
        "max_video_duration": MAX_VIDEO_DURATION,
        "default_num_clips": DEFAULT_NUM_CLIPS
    })


@app.route("/api/video-info", methods=["POST"])
def api_video_info():
    """Get video metadata from URL."""
    data = request.get_json() or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    info = get_video_info(url)
    if info:
        return jsonify(info)
    return jsonify({"error": "Could not fetch video info. Please verify the URL."}), 400


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload a local video file directly (supports multi-hour files up to 16GB)."""
    if 'video' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['video']
    if not file or file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    num_clips = int(request.form.get("num_clips", DEFAULT_NUM_CLIPS))
    job_id = uuid.uuid4().hex[:12]
    ext = Path(file.filename).suffix or ".mp4"
    saved_filename = f"{job_id}{ext}"
    saved_path = DOWNLOADS_DIR / saved_filename
    file.save(str(saved_path))

    jobs[job_id] = {
        "id": job_id,
        "url": file.filename,
        "title": file.filename,
        "status": "queued",
        "message": "Local video uploaded. Inspecting timeline...",
        "video_path": str(saved_path),
        "transcript": [],
        "suggestions": [],
        "clips": [],
        "duration": 0,
        "num_clips": num_clips,
        "created_at": time.time(),
    }

    thread = threading.Thread(
        target=process_video_pipeline,
        args=(None, job_id, True, str(saved_path), num_clips)
    )
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "message": "Upload complete, pipeline running!"})


@app.route("/api/process", methods=["POST"])
def api_process():
    """Start video processing pipeline from URL with requested clip count."""
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    num_clips = int(data.get("num_clips", DEFAULT_NUM_CLIPS))

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "status": "queued",
        "message": "Starting video analysis...",
        "video_path": None,
        "transcript": [],
        "suggestions": [],
        "clips": [],
        "duration": 0,
        "num_clips": num_clips,
        "created_at": time.time(),
    }

    thread = threading.Thread(target=process_video_pipeline, args=(url, job_id, False, None, num_clips))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "message": "Processing started!"})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    """Check processing status and retrieve suggestions."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    return jsonify({
        "id": job.get("id", job_id),
        "status": job.get("status", "unknown"),
        "message": job.get("message", ""),
        "duration": job.get("duration", 0),
        "duration_str": format_timestamp(job.get("duration", 0)),
        "transcript": job.get("transcript", []),
        "suggestions": job.get("suggestions", []),
        "clips": job.get("clips", []),
        "num_clips": job.get("num_clips", DEFAULT_NUM_CLIPS),
        "has_transcript": len(job.get("transcript", [])) > 0,
        "has_suggestions": len(job.get("suggestions", [])) > 0,
    })


@app.route("/api/clip", methods=["POST"])
def api_create_clip():
    """
    Create a 9:16 clip from processed video with fast or high quality and optional subtitles.
    Works for online URLs and local video files, including multi-hour content.
    """
    data = request.get_json() or {}
    job_id = data.get("job_id")
    start = float(data.get("start", 0))
    end = float(data.get("end", 0))
    name = data.get("name", "clip")
    aspect_ratio = data.get("aspect_ratio", DEFAULT_ASPECT_RATIO)
    quality = data.get("quality", "fast")
    with_subtitles = bool(data.get("subtitles", True))

    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    video_path = job.get("video_path")
    url = job.get("url")

    if end <= start:
        return jsonify({"error": "End time must be greater than start time"}), 400

    if end - start > 600:
        return jsonify({"error": "Single clip duration must be under 10 minutes"}), 400

    # If local video file is present, clip directly
    if video_path and os.path.exists(video_path):
        result = create_clip_from_local(video_path, start, end, name, job_id, aspect_ratio, quality, with_subtitles=with_subtitles)
    elif url:
        result = create_clip_from_url(url, start, end, name, job_id, aspect_ratio, quality, with_subtitles=with_subtitles)
    else:
        return jsonify({"error": "No source video available to clip"}), 400

    if result.get("success"):
        job["clips"].append(result)
        return jsonify(result)
    else:
        return jsonify({"error": result.get("error", "Failed to render clip")}), 500


@app.route("/api/batch-clip", methods=["POST"])
def api_batch_clip():
    """Render all suggested clips in batch for one-click ZIP download."""
    data = request.get_json() or {}
    job_id = data.get("job_id")
    aspect_ratio = data.get("aspect_ratio", DEFAULT_ASPECT_RATIO)
    quality = data.get("quality", "fast")
    with_subtitles = bool(data.get("subtitles", True))

    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    suggestions = job.get("suggestions", [])
    if not suggestions:
        return jsonify({"error": "No suggestions available to render"}), 400

    video_path = job.get("video_path")
    url = job.get("url")

    # Render each suggestion that isn't already created
    created_filenames = {c.get("title") for c in job.get("clips", [])}
    rendered_count = 0

    for idx, s in enumerate(suggestions):
        if s.get("title") in created_filenames:
            continue
        start = s.get("start_seconds", 0)
        end = s.get("end_seconds", 30)
        name = s.get("title", f"Clip {idx+1}")

        if video_path and os.path.exists(video_path):
            res = create_clip_from_local(video_path, start, end, name, job_id, aspect_ratio, quality, with_subtitles=with_subtitles)
        elif url:
            res = create_clip_from_url(url, start, end, name, job_id, aspect_ratio, quality, with_subtitles=with_subtitles)
        else:
            continue

        if res.get("success"):
            job["clips"].append(res)
            rendered_count += 1

    return jsonify({
        "success": True,
        "rendered_count": rendered_count,
        "total_clips": len(job.get("clips", [])),
        "download_zip_url": f"/api/download-all/{job_id}"
    })


@app.route("/api/download-clip/<filename>")
def api_download_clip(filename):
    """Download a created clip with attachment header and friendly filename."""
    clip_path = CLIPS_DIR / filename
    if clip_path.exists():
        friendly_name = request.args.get("name", "").strip()
        if not friendly_name:
            friendly_name = filename
        if not friendly_name.endswith(f".{CLIP_FORMAT}"):
            friendly_name = f"{friendly_name}.{CLIP_FORMAT}"
        friendly_name = re.sub(r'[^\w\-_\. ]', '_', friendly_name)

        return send_file(
            str(clip_path),
            as_attachment=True,
            download_name=friendly_name,
            mimetype="video/mp4"
        )
    return jsonify({"error": "Clip file not found"}), 404


@app.route("/api/download-all/<job_id>")
def api_download_all(job_id):
    """Download all clips for a job in a single ZIP file."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    clips = job.get("clips", [])
    if not clips:
        return jsonify({"error": "No clips created yet. Render some clips first!"}), 400

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, c in enumerate(clips):
            fname = c.get("filename")
            if fname:
                c_path = CLIPS_DIR / fname
                if c_path.exists():
                    clean_title = re.sub(r'[^\w\-_\. ]', '_', c.get('title', f'clip_{idx+1}'))
                    zip_name = f"{idx+1:02d}_{clean_title}_9x16.{CLIP_FORMAT}"
                    zf.write(str(c_path), arcname=zip_name)

    mem_zip.seek(0)
    video_title = re.sub(r'[^\w\-_\. ]', '_', job.get("title", f"clips_{job_id}"))[:30]
    return send_file(
        mem_zip,
        as_attachment=True,
        download_name=f"{video_title}_9x16_Clips.zip",
        mimetype="application/zip"
    )


@app.route("/clips/<filename>")
def serve_clip(filename):
    """Stream clip for inline HTML5 video player."""
    return send_from_directory(str(CLIPS_DIR), filename)


@app.route("/api/cleanup/<job_id>", methods=["DELETE"])
def api_cleanup(job_id):
    """Clean up downloaded files for a job."""
    if job_id in jobs:
        job = jobs[job_id]
        video_path = job.get("video_path")
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass
        del jobs[job_id]
        return jsonify({"message": "Cleaned up successfully"})
    return jsonify({"error": "Job not found"}), 404


# ===================== MAIN =====================

if __name__ == "__main__":
    has_gemini = bool(GEMINI_API_KEY and GEMINI_API_KEY not in ["your_gemini_api_key_here", "your_actual_key_here"])

    print("\n" + "=" * 65)
    print("  🎬  AI Video Clipper (9:16 Fast & HD Vertical Clips)")
    print("=" * 65)
    print(f"  Downloads:      {DOWNLOADS_DIR}")
    print(f"  Clips:          {CLIPS_DIR}")
    print(f"  Default Ratio:  9:16 Vertical (Blur Background)")
    print(f"  Fast Download:  ⚡ Enabled (Instant render + ZIP export)")
    print(f"  Clips Default:  {DEFAULT_NUM_CLIPS} clips (User configurable)")
    print(f"  Max Duration:   No Limit (Hours Supported)")
    print(f"  Max Upload:     16 GB")
    print(f"  Whisper Model:  {WHISPER_MODEL}")
    print(f"  Gemini AI:      {'✅ Configured' if has_gemini else '⚠️ Not set (Using Smart Moment Suggestions)'}")
    print(f"  FFmpeg:         {FFMPEG_PATH}")
    print("=" * 65)
    print("  Open http://localhost:5000 in your browser")
    print("=" * 65 + "\n")

    app.run(debug=True, host="0.0.0.0", port=5000)
