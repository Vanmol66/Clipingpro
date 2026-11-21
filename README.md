# 🎬 AI Video Clipper

A powerful web-based tool that downloads online videos, transcribes them with AI (Whisper), 
uses Gemini AI to find the most interesting moments, and lets you create clips with one click.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **🌐 1000+ Sites** | Download videos from YouTube, Twitter/X, Instagram, TikTok, Reddit, Vimeo, and 1000+ more |
| **🎙️ AI Transcription** | OpenAI Whisper transcribes audio with word-level timestamps |
| **🤖 Smart Suggestions** | Gemini AI analyzes the transcript and suggests the best clip moments |
| **✂️ Precise Clipping** | Create clips from AI suggestions or set custom start/end times |
| **📥 Instant Download** | Preview and download clips in MP4 format |
| **🎨 Modern UI** | Beautiful dark-themed interface with smooth animations |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- **FFmpeg** — [Download here](https://ffmpeg.org/download.html) and add to PATH
- **Gemini API Key** (free) — [Get one here](https://aistudio.google.com/apikey)

### 1. Install Dependencies

```bash
cd ai-video-clipper
pip install -r requirements.txt
```

> **Note:** The first run will download the Whisper model (~140MB for 'base'). 
> For faster transcription on GPU, install PyTorch with CUDA support.

### 2. Configure

Copy the example env file and add your Gemini API key:

```bash
copy .env.example .env
```

Edit `.env` and set your `GEMINI_API_KEY`:

```env
GEMINI_API_KEY=your_actual_key_here
WHISPER_MODEL=base
```

### 3. Run

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

---

## 📖 How to Use

1. **Paste a URL** — Enter any video link (YouTube, Twitter, etc.)
2. **Preview** — Click "Preview" to see video info before processing
3. **Process** — Click "Process & Clip" to start the AI pipeline:
   - ⬇️ Downloads the video
   - 🎙️ Transcribes audio with Whisper
   - 🤖 Gemini AI analyzes and suggests best clips
4. **Create Clips** — Click an AI suggestion or set custom timestamps
5. **Download** — Preview and download your clips

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | _(required)_ | Your Google Gemini API key |
| `WHISPER_MODEL` | `base` | Whisper model: `tiny`, `base`, `small`, `medium`, `large` |
| `MAX_VIDEO_DURATION` | `3600` | Max video length in seconds (0 = no limit) |
| `CLIP_FORMAT` | `mp4` | Output format for clips |

### Whisper Model Sizes

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny` | 39MB | Fastest | Basic |
| `base` | 74MB | Fast | Good |
| `small` | 244MB | Medium | Better |
| `medium` | 769MB | Slow | Great |
| `large` | 1.5GB | Slowest | Best |

---

## 🏗️ Project Structure

```
ai-video-clipper/
├── app.py                  # Flask backend + API routes
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
├── static/
│   ├── css/
│   │   └── style.css       # UI styles (dark theme)
│   └── js/
│       └── app.js          # Frontend JavaScript
├── templates/
│   └── index.html          # Main page template
├── downloads/              # Temporary video downloads
└── clips/                  # Generated clips (output)
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| FFmpeg not found | Install FFmpeg and add to PATH. [Guide](https://ffmpeg.org/download.html) |
| Whisper fails | Ensure `torch` is installed. For GPU: install CUDA-enabled PyTorch |
| No AI suggestions | Check your `GEMINI_API_KEY` in `.env` |
| Download fails | Some sites require cookies. Try updating yt-dlp: `pip install -U yt-dlp` |

---

## 📄 License

MIT License — use it however you like!
