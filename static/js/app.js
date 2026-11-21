/**
 * AI Video Clipper - Frontend Logic
 * Supports 9:16 Vertical Video, Fast Download, ZIP Export & Configurable Clip Quantities
 */

// ===================== STATE =====================
let currentJobId = null;
let pollInterval = null;
let videoInfo = null;
let selectedFile = null;
let currentAspectRatio = '9:16_blur';
let currentClipCount = 8;
let currentSpeedMode = 'fast'; // 'fast' or 'high'
let currentSubtitlesMode = true; // true (default) or false
let hamsterPunchlineInterval = null;
let truckPunchlineInterval = null;

const FUNNY_PUNCHLINES = [
    "🐹 Our AI hamster is sprinting on the wheel to power the GPU...",
    "🏃‍♂️ Running at 120 RPM through your video's timeline...",
    "🔍 Sniffing out the absolute funniest moments and skipping the boring intros...",
    "🎬 Calculating exact TikTok & Reels virality coefficients...",
    "🧀 Fueled by sunflower seeds and pure algorithmic instinct...",
    "⚡ Trimming out the awkward silences so you look like a content genius...",
    "🧠 Teaching the AI hamster how to crop 16:9 into flawless 9:16...",
    "🔥 Finding the moment where everyone in the comments will type 'LMAOO'...",
    "📦 Preparing your high-definition clips and stuffing cheek pouches with data...",
    "🚀 Almost at the finish line! Getting the download buttons ready..."
];

const TRUCK_PUNCHLINES = [
    "🚚 Honk honk! Your vertical 9:16 clips are loaded onto the delivery truck...",
    "🛣️ Speeding down the GPU highway with zero traffic delays...",
    "📦 Handle with care: Highly viral content inside this cargo!",
    "💨 Drifting around corners to get your MP4 downloads to you faster...",
    "⛽ Refueling on pure CPU horsepower and delivering fresh 1080p pixels...",
    "📍 GPS route updated: Destination -> Your Downloads folder!",
    "🎶 Driver has the radio turned up while FFmpeg stitches the frames...",
    "🚦 Green lights all the way — your clips will arrive any second!"
];

function startHamsterPunchlines() {
    stopHamsterPunchlines();
    const elem = $('#hamster-punchline');
    if (!elem) return;
    let idx = 0;
    elem.textContent = FUNNY_PUNCHLINES[0];
    hamsterPunchlineInterval = setInterval(() => {
        idx = (idx + 1) % FUNNY_PUNCHLINES.length;
        elem.style.opacity = '0';
        setTimeout(() => {
            elem.textContent = FUNNY_PUNCHLINES[idx];
            elem.style.opacity = '1';
        }, 300);
    }, 3200);
}

function stopHamsterPunchlines() {
    if (hamsterPunchlineInterval) {
        clearInterval(hamsterPunchlineInterval);
        hamsterPunchlineInterval = null;
    }
}

function showTruckLoader(customText = null) {
    stopTruckLoader();
    const container = $('#truck-delivery-loader');
    const punchline = $('#truck-punchline');
    if (!container || !punchline) return;

    container.style.display = 'flex';
    container.scrollIntoView({ behavior: 'smooth', block: 'center' });

    let idx = 0;
    punchline.textContent = customText || TRUCK_PUNCHLINES[0];

    truckPunchlineInterval = setInterval(() => {
        idx = (idx + 1) % TRUCK_PUNCHLINES.length;
        punchline.style.opacity = '0';
        setTimeout(() => {
            punchline.textContent = TRUCK_PUNCHLINES[idx];
            punchline.style.opacity = '1';
        }, 300);
    }, 3000);
}

function stopTruckLoader() {
    if (truckPunchlineInterval) {
        clearInterval(truckPunchlineInterval);
        truckPunchlineInterval = null;
    }
    const container = $('#truck-delivery-loader');
    if (container) {
        container.style.display = 'none';
    }
}

// ===================== DOM REFS =====================
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ===================== TOAST =====================
function showToast(message, type = 'info') {
    const container = $('.toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'}</span> <div>${escapeHtml(message)}</div>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.4s ease forwards';
        setTimeout(() => toast.remove(), 400);
    }, 4500);
}

// ===================== TABS, RATIO, COUNT & SPEED =====================
function switchInputTab(tab) {
    if (tab === 'url') {
        $('#tab-url-btn').classList.add('active');
        $('#tab-upload-btn').classList.remove('active');
        $('#tab-url').style.display = 'block';
        $('#tab-upload').style.display = 'none';
    } else {
        $('#tab-upload-btn').classList.add('active');
        $('#tab-url-btn').classList.remove('active');
        $('#tab-upload').style.display = 'block';
        $('#tab-url').style.display = 'none';
    }
}

function setClipCount(count) {
    const num = Math.max(1, Math.min(25, parseInt(count) || 8));
    currentClipCount = num;

    $$('.count-pill').forEach(pill => {
        const pillVal = parseInt(pill.textContent);
        pill.classList.toggle('active', pillVal === num);
    });

    const customInput = $('#custom-clip-count');
    if (customInput && parseInt(customInput.value) !== num) {
        customInput.value = num;
    }
}

function updateSpeedSelection(radio) {
    currentSpeedMode = radio.value;
    $('#speed-pill-fast').classList.toggle('active', currentSpeedMode === 'fast');
    $('#speed-pill-high').classList.toggle('active', currentSpeedMode === 'high');
}

function updateSubtitlesSelection(radio) {
    currentSubtitlesMode = (radio.value === 'on');
    $('#sub-pill-off').classList.toggle('active', !currentSubtitlesMode);
    $('#sub-pill-on').classList.toggle('active', currentSubtitlesMode);
    const subManual = $('#clip-subtitles-manual');
    if (subManual) subManual.value = currentSubtitlesMode ? 'on' : 'off';
}

function updateAspectSelection(radio) {
    currentAspectRatio = radio.value;
    $$('.ratio-pill').forEach(pill => {
        pill.classList.toggle('active', pill.querySelector('input').value === currentAspectRatio);
    });
    const formSelect = $('#clip-aspect-ratio');
    if (formSelect) formSelect.value = currentAspectRatio;
}

// ===================== LOCAL FILE UPLOAD =====================
function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        setUploadFile(file);
    }
}

function setUploadFile(file) {
    selectedFile = file;
    const label = $('#upload-label');
    const startBtn = $('#start-upload-btn');
    const sizeMb = (file.size / (1024 * 1024)).toFixed(1);

    label.innerHTML = `📄 <strong>${escapeHtml(file.name)}</strong> (${sizeMb} MB)`;
    startBtn.style.display = 'inline-block';
}

function uploadVideoFile() {
    if (!selectedFile) {
        showToast('Please select a video file first', 'error');
        return;
    }

    const btn = $('#start-upload-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Uploading...';

    // Reset progress
    if (pollInterval) clearInterval(pollInterval);
    currentJobId = null;

    const progressSection = $('.progress-section');
    progressSection.classList.add('visible');
    $('.results-section').classList.remove('visible');

    const steps = $$('.progress-step');
    steps.forEach(s => s.classList.remove('active', 'done'));
    steps[0].classList.add('active');

    const bar = $('.progress-bar-fill');
    const msg = $('.progress-message');
    bar.style.width = '0%';
    msg.innerHTML = '<span class="spinner"></span> Starting upload...';

    const formData = new FormData();
    formData.append('video', selectedFile);
    formData.append('num_clips', currentClipCount);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload', true);

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            const loadedMb = (e.loaded / (1024 * 1024)).toFixed(1);
            const totalMb = (e.total / (1024 * 1024)).toFixed(1);
            bar.style.width = Math.min(95, percent) + '%';
            msg.innerHTML = `<span class="spinner"></span> Uploading: ${percent}% (${loadedMb} MB / ${totalMb} MB)...`;
        }
    };

    xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                const data = JSON.parse(xhr.responseText);
                if (data.error) {
                    showToast(data.error, 'error');
                    btn.disabled = false;
                    btn.innerHTML = '🚀 Upload & Process';
                    return;
                }

                currentJobId = data.job_id;
                showToast(`Video uploaded! Generating ${currentClipCount} 9:16 clips...`, 'success');

                startHamsterPunchlines();
                pollInterval = setInterval(() => pollStatus(), 2000);
                pollStatus();

            } catch (err) {
                showToast('Error reading upload response: ' + err.message, 'error');
                btn.disabled = false;
                btn.innerHTML = '🚀 Upload & Process';
            }
        } else {
            let errorMsg = `Upload failed (${xhr.status})`;
            try {
                const errData = JSON.parse(xhr.responseText);
                if (errData.error) errorMsg = errData.error;
            } catch (_) {
                if (xhr.status === 413) {
                    errorMsg = 'File is too large (exceeds 16GB limit).';
                }
            }
            showToast(errorMsg, 'error');
            btn.disabled = false;
            btn.innerHTML = '🚀 Upload & Process';
            msg.innerHTML = '❌ ' + errorMsg;
            bar.style.width = '0%';
        }
    };

    xhr.onerror = () => {
        showToast('Network error during file upload', 'error');
        btn.disabled = false;
        btn.innerHTML = '🚀 Upload & Process';
        msg.innerHTML = '❌ Upload failed due to network error';
    };

    xhr.send(formData);
}

// Drag & drop setup
document.addEventListener('DOMContentLoaded', () => {
    const dropzone = $('#dropzone');
    if (dropzone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropzone.classList.add('dragover');
            }, false);
        });
        ['dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropzone.classList.remove('dragover');
            }, false);
        });
        dropzone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files[0]) {
                setUploadFile(files[0]);
            }
        });
    }

    // Load initial settings/status
    loadAppConfig();
});

// ===================== FETCH VIDEO INFO =====================
async function fetchVideoInfo() {
    const url = $('#url-input').value.trim();
    if (!url) {
        showToast('Please enter a video URL', 'error');
        return;
    }

    const btn = $('#preview-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Loading...';

    try {
        const res = await fetch('/api/video-info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await res.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        videoInfo = data;
        const preview = $('.video-preview');
        preview.classList.add('visible');
        preview.innerHTML = `
            <img src="${data.thumbnail}" alt="Thumbnail" onerror="this.style.display='none'">
            <div class="info">
                <h3>${escapeHtml(data.title)}</h3>
                <p>👤 ${escapeHtml(data.uploader)}</p>
                <p>⏱️ Duration: <strong>${data.duration_str}</strong> &nbsp;|&nbsp; 👁️ ${formatNumber(data.view_count)} views</p>
                <span class="badge">Ready for ${currentClipCount} 9:16 Clips</span>
            </div>
        `;

        $('#process-btn').disabled = false;

    } catch (err) {
        showToast('Failed to fetch video info: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔍 Preview';
    }
}

// ===================== PROCESS VIDEO =====================
async function processVideo() {
    const url = $('#url-input').value.trim();
    if (!url) {
        showToast('Please enter a video URL', 'error');
        return;
    }

    // Reset state
    if (pollInterval) clearInterval(pollInterval);
    currentJobId = null;

    // Show progress
    const progressSection = $('.progress-section');
    progressSection.classList.add('visible');
    $('.results-section').classList.remove('visible');

    const btn = $('#process-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Processing...';

    try {
        const res = await fetch('/api/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                num_clips: currentClipCount
            })
        });

        const data = await res.json();

        if (data.error) {
            showToast(data.error, 'error');
            btn.disabled = false;
            btn.innerHTML = '🚀 Process & Clip (9:16)';
            return;
        }

        currentJobId = data.job_id;
        showToast(`Analyzing video timeline for ${currentClipCount} clips...`, 'success');

        // Start polling & hamster animation quotes
        startHamsterPunchlines();
        pollInterval = setInterval(() => pollStatus(), 2000);
        pollStatus();

    } catch (err) {
        showToast('Failed to start processing: ' + err.message, 'error');
        btn.disabled = false;
        btn.innerHTML = '🚀 Process & Clip (9:16)';
    }
}

// ===================== POLL STATUS =====================
async function pollStatus() {
    if (!currentJobId) return;

    try {
        const res = await fetch(`/api/status/${currentJobId}`);
        const data = await res.json();

        updateProgress(data);

        if (data.status === 'ready' || data.status === 'error') {
            clearInterval(pollInterval);
            pollInterval = null;

            const btn = $('#process-btn');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🚀 Process & Clip (9:16)';
            }

            if (data.status === 'ready') {
                showResults(data);
                showToast(`Ready! ${data.suggestions.length} viral 9:16 clip moments generated.`, 'success');
            } else {
                showToast(data.message || 'Error processing video', 'error');
            }
        }

    } catch (err) {
        console.error('Poll error:', err);
    }
}

// ===================== UPDATE PROGRESS UI =====================
function updateProgress(data) {
    const steps = $$('.progress-step');
    const bar = $('.progress-bar-fill');
    const msg = $('.progress-message');

    steps.forEach(s => { s.classList.remove('active', 'done'); });

    let progress = 0;

    switch (data.status) {
        case 'queued':
            progress = 10;
            msg.innerHTML = '<span class="spinner"></span> Starting pipeline...';
            break;
        case 'downloading':
            steps[0].classList.add('active');
            progress = 30;
            msg.innerHTML = '<span class="spinner"></span> ' + escapeHtml(data.message);
            break;
        case 'processing':
            steps[0].classList.add('done');
            steps[1].classList.add('active');
            progress = 50;
            msg.innerHTML = '<span class="spinner"></span> ' + escapeHtml(data.message);
            break;
        case 'transcribing':
            steps[0].classList.add('done');
            steps[1].classList.add('active');
            progress = 70;
            msg.innerHTML = '<span class="spinner"></span> ' + escapeHtml(data.message);
            break;
        case 'analyzing':
            steps[0].classList.add('done');
            steps[1].classList.add('done');
            steps[2].classList.add('active');
            progress = 90;
            msg.innerHTML = '<span class="spinner"></span> ' + escapeHtml(data.message);
            break;
        case 'ready':
            steps.forEach(s => s.classList.add('done'));
            progress = 100;
            msg.innerHTML = '✅ ' + escapeHtml(data.message);
            break;
        case 'error':
            progress = 0;
            msg.innerHTML = '❌ ' + escapeHtml(data.message);
            break;
    }

    bar.style.width = progress + '%';
}

// ===================== SHOW RESULTS =====================
function showResults(data) {
    stopHamsterPunchlines();
    const resultsSection = $('.results-section');
    resultsSection.classList.add('visible');

    const countElem = $('#suggestions-count');
    if (countElem) countElem.textContent = (data.suggestions || []).length;

    // Render AI suggestions
    renderSuggestions(data.suggestions || []);

    // Render transcript
    renderTranscript(data.transcript || []);

    // Set initial end time
    if (data.duration) {
        $('#clip-end').value = formatTimestamp(Math.min(30, data.duration));
    }

    // Batch download setup
    updateBatchActions(data.clips || []);

    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ===================== RENDER AI SUGGESTIONS =====================
function renderSuggestions(suggestions) {
    const grid = $('#suggestions-grid');

    if (!suggestions || suggestions.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1; padding: 30px;">
                <div class="icon">🤖</div>
                <h3>No suggestions generated</h3>
                <p>Use the custom clip creator below to set timestamps and render a 9:16 clip.</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = suggestions.map((clip, i) => {
        const scoreClass = clip.score >= 8 ? 'score-high' : clip.score >= 5 ? 'score-mid' : 'score-low';
        return `
            <div class="suggestion-card">
                <div class="card-header">
                    <div class="card-title">${escapeHtml(clip.title)}</div>
                    <span class="score-badge ${scoreClass}">🔥 ${clip.score}/10</span>
                </div>
                <div class="card-time">⏱ ${clip.start} → ${clip.end}</div>
                <div class="card-reason">${escapeHtml(clip.reason)}</div>
                <div class="card-actions">
                    <button class="btn btn-fast-dl btn-sm" onclick="quickRenderAndDownload(${i}, this)">
                        ⚡ Fast Download
                    </button>
                    <button class="btn btn-primary btn-sm" onclick="createClipFromSuggestion(${i}, this)">
                        📱 Render & Preview
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

// ===================== RENDER TRANSCRIPT =====================
function renderTranscript(segments) {
    const body = $('#transcript-body');

    if (!segments || segments.length === 0) {
        body.innerHTML = `
            <div class="empty-state" style="padding: 24px;">
                <p>No transcript segments available for this video</p>
            </div>
        `;
        return;
    }

    body.innerHTML = segments.map(seg => `
        <div class="transcript-segment" onclick="fillClipForm('${seg.start_str}', '${seg.end_str}', 'Clip ${seg.start_str}')">
            <span class="ts">${seg.start_str}</span>
            <span class="text">${escapeHtml(seg.text)}</span>
        </div>
    `).join('');
}

function toggleTranscript() {
    $('#transcript-body').classList.toggle('open');
    const arrow = $('#transcript-arrow');
    arrow.textContent = $('#transcript-body').classList.contains('open') ? '▲' : '▼';
}

// ===================== CLIP CREATION (9:16 & FAST DOWNLOAD) =====================
function fillClipForm(start, end, name) {
    $('#clip-start').value = start;
    $('#clip-end').value = end;
    $('#clip-name').value = name;

    const creator = document.querySelector('.clip-creator');
    if (creator) {
        creator.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

async function quickRenderAndDownload(index, btn = null) {
    if (!currentJobId) return;

    let originalHtml = '';
    if (btn) {
        btn.disabled = true;
        originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner"></span> Fast Rendering...';
    }

    try {
        const statusRes = await fetch(`/api/status/${currentJobId}`);
        const statusData = await statusRes.json();
        const clip = statusData.suggestions[index];

        if (clip) {
            const clipResult = await createClip(clip.start, clip.end, clip.title, currentAspectRatio, currentSpeedMode, currentSubtitlesMode);
            if (clipResult && clipResult.download_url) {
                // Instantly trigger browser download
                window.location.href = clipResult.download_url;
                showToast(`⚡ Downloading ${clip.title} MP4!`, 'success');
            }
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}

async function createClipFromSuggestion(index, btn = null) {
    if (!currentJobId) return;

    let originalHtml = '';
    if (btn) {
        btn.disabled = true;
        originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner"></span> Rendering 9:16...';
    }

    try {
        const statusRes = await fetch(`/api/status/${currentJobId}`);
        const statusData = await statusRes.json();
        const clip = statusData.suggestions[index];

        if (clip) {
            await createClip(clip.start, clip.end, clip.title, currentAspectRatio, currentSpeedMode, currentSubtitlesMode);
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}

async function createClipManual() {
    const start = $('#clip-start').value.trim();
    const end = $('#clip-end').value.trim();
    const name = $('#clip-name').value.trim() || 'clip';
    const formSelect = $('#clip-aspect-ratio');
    const ratio = formSelect ? formSelect.value : currentAspectRatio;
    const subSelect = $('#clip-subtitles-manual');
    const subtitles = subSelect ? (subSelect.value === 'on') : currentSubtitlesMode;

    if (!start || !end) {
        showToast('Please enter start and end times', 'error');
        return;
    }

    await createClip(start, end, name, ratio, currentSpeedMode, subtitles);
}

async function createClip(start, end, name, aspectRatio = '9:16_blur', quality = 'fast', subtitles = false) {
    if (!currentJobId) {
        showToast('No video loaded. Process a video first.', 'error');
        return null;
    }

    let startSec, endSec;
    try {
        startSec = parseTimestamp(start);
        endSec = parseTimestamp(end);
    } catch (e) {
        showToast('Invalid timestamp format. Use HH:MM:SS', 'error');
        return null;
    }

    if (endSec <= startSec) {
        showToast('End time must be after start time', 'error');
        return null;
    }

    const btn = $('#create-clip-btn');
    if (btn) {
        btn.disabled = true;
        const subNote = subtitles ? ' + Subtitles' : '';
        btn.innerHTML = `<span class="spinner"></span> Rendering 9:16 Clip (${quality === 'fast' ? 'Fast Mode' : 'HD 1080p'}${subNote})...`;
    }

    showTruckLoader("🚚 Delivering your 9:16 vertical clip! Hang tight...");

    try {
        const res = await fetch('/api/clip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentJobId,
                start: startSec,
                end: endSec,
                name: name,
                aspect_ratio: aspectRatio,
                quality: quality,
                subtitles: subtitles
            })
        });

        const data = await res.json();

        if (data.error) {
            showToast(data.error, 'error');
            return null;
        }

        showToast(`✅ 9:16 Clip Rendered! (${data.duration_str}, ${data.size_mb} MB)`, 'success');
        addClipToList(data, name);

        // Update batch actions
        const statusRes = await fetch(`/api/status/${currentJobId}`);
        const statusData = await statusRes.json();
        updateBatchActions(statusData.clips || []);

        return data;

    } catch (err) {
        showToast('Failed to render clip: ' + err.message, 'error');
        return null;
    } finally {
        stopTruckLoader();
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '⚡ Render 9:16 Clip';
        }
    }
}

// ===================== BATCH RENDER & ZIP EXPORT =====================
async function batchRenderAllAndZip() {
    if (!currentJobId) {
        showToast('No video active. Process a video first.', 'error');
        return;
    }

    const btn = $('#batch-render-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Batch Rendering All Clips...';

    showToast('Starting batch 9:16 render for all suggestions...', 'info');
    showTruckLoader("🚚 Delivery fleet dispatched! Batch rendering all clips & packaging into ZIP...");

    try {
        const res = await fetch('/api/batch-clip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentJobId,
                aspect_ratio: currentAspectRatio,
                quality: currentSpeedMode,
                subtitles: currentSubtitlesMode
            })
        });

        const data = await res.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        // Fetch refreshed clips
        const statusRes = await fetch(`/api/status/${currentJobId}`);
        const statusData = await statusRes.json();

        const clips = statusData.clips || [];
        const list = $('#clips-list');
        list.innerHTML = '';
        clips.forEach(c => addClipToList(c, c.title));

        updateBatchActions(clips);

        showToast(`🎉 All ${clips.length} clips rendered! Downloading ZIP now...`, 'success');

        // Automatically trigger ZIP download
        window.location.href = `/api/download-all/${currentJobId}`;

    } catch (err) {
        showToast('Batch render failed: ' + err.message, 'error');
    } finally {
        stopTruckLoader();
        btn.disabled = false;
        btn.innerHTML = '🚀 Generate All Clips & Download ZIP';
    }
}

function addClipToList(clipData, name) {
    const list = $('#clips-list');
    const emptyState = list.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const cleanTitle = encodeURIComponent((name || 'clip').replace(/[^\w\-_\. ]/g, '_'));
    const downloadHref = `/api/download-clip/${clipData.filename}?name=${cleanTitle}_9x16`;

    const card = document.createElement('div');
    card.className = 'clip-card';
    card.innerHTML = `
        <div class="clip-video-wrap">
            <span class="clip-aspect-badge">📱 ${clipData.ratio_label || '9:16 Vertical'}</span>
            <video controls preload="metadata" playsinline>
                <source src="/clips/${clipData.filename}" type="video/mp4">
            </video>
        </div>
        <div class="clip-info">
            <h4>${escapeHtml(name || 'Clip')}</h4>
            <div class="meta">
                ⏱ ${clipData.duration_str} &nbsp;|&nbsp; 📦 ${clipData.size_mb} MB &nbsp;|&nbsp; ⚡ ${clipData.quality || 'Fast 9:16'}
            </div>
            <div class="clip-actions">
                <a href="${downloadHref}" class="btn btn-fast-dl btn-sm" download="${escapeHtml(name || 'clip')}_9x16.mp4">
                    ⚡ Fast Download MP4
                </a>
                <button class="btn btn-secondary btn-sm" onclick="copyClipLink('/clips/${clipData.filename}')">
                    📋 Link
                </button>
            </div>
        </div>
    `;
    list.prepend(card);

    const renderedCountElem = $('#rendered-count');
    if (renderedCountElem) {
        const total = list.querySelectorAll('.clip-card').length;
        renderedCountElem.textContent = total;
    }
}

function updateBatchActions(clips) {
    const batchDiv = $('#batch-actions');
    const dlAllBtn = $('#download-all-btn');
    const renderedCountElem = $('#rendered-count');

    const total = clips ? clips.length : 0;
    if (renderedCountElem) renderedCountElem.textContent = total;

    if (clips && clips.length > 0 && currentJobId) {
        if (batchDiv) batchDiv.style.display = 'block';
        if (dlAllBtn) {
            dlAllBtn.href = `/api/download-all/${currentJobId}`;
            dlAllBtn.innerHTML = `📦 Download All as ZIP (${total} clips)`;
        }
    } else {
        if (batchDiv) batchDiv.style.display = 'none';
    }
}

function copyClipLink(path) {
    const fullUrl = window.location.origin + path;
    navigator.clipboard.writeText(fullUrl).then(() => {
        showToast('Clip link copied to clipboard!', 'success');
    }).catch(() => {
        showToast('Link: ' + fullUrl, 'info');
    });
}

// ===================== SETTINGS & API CONFIG =====================
function toggleSettingsModal() {
    const modal = $('#settings-modal');
    if (!modal) return;
    const isVisible = modal.style.display !== 'none';
    modal.style.display = isVisible ? 'none' : 'flex';
    if (!isVisible) {
        loadAppConfig();
    }
}

async function loadAppConfig() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        const navStatus = $('#api-status-text');
        const geminiInd = $('#settings-status-indicator');
        const groqInd = $('#groq-status-indicator');

        // Status Indicators
        if (groqInd) {
            groqInd.innerHTML = data.groq_configured
                ? '<span style="color: var(--success);">✅ Groq Llama 3.3 70B & Whisper Large v3 Active</span>'
                : '<span style="color: var(--text-secondary);">⚪ Optional (Enter key for ultra-fast Llama 3.3 70B analysis)</span>';
        }

        if (geminiInd) {
            geminiInd.innerHTML = data.gemini_configured
                ? '<span style="color: var(--success);">✅ Gemini 2.0 / 1.5 Flash Active</span>'
                : '<span style="color: var(--text-secondary);">⚪ Optional (Enter key for Gemini viral moment discovery)</span>';
        }

        if (navStatus) {
            if (data.groq_configured && data.gemini_configured) {
                navStatus.innerHTML = '⚡ Groq & Gemini Active';
            } else if (data.groq_configured) {
                navStatus.innerHTML = '⚡ Groq (Llama 3.3) Active';
            } else if (data.gemini_configured) {
                navStatus.innerHTML = '🤖 Gemini Active';
            } else {
                navStatus.innerHTML = '⚙️ AI Models & API Keys';
            }
        }

        if (data.default_num_clips) {
            setClipCount(data.default_num_clips);
        }
    } catch (e) {
        console.error('Config fetch error', e);
    }
}

async function saveApiKeys() {
    const groqKey = $('#settings-groq-key').value.trim();
    const geminiKey = $('#settings-api-key').value.trim();

    if (!groqKey && !geminiKey) {
        showToast('Please enter a Groq or Gemini API key', 'error');
        return;
    }

    try {
        const payload = {};
        if (groqKey) payload.groq_api_key = groqKey;
        if (geminiKey) payload.gemini_api_key = geminiKey;

        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast('AI Keys saved & activated!', 'success');
            $('#settings-groq-key').value = '';
            $('#settings-api-key').value = '';
            toggleSettingsModal();
            loadAppConfig();
        } else {
            showToast(data.error || 'Failed to save keys', 'error');
        }
    } catch (e) {
        showToast('Error saving keys: ' + e.message, 'error');
    }
}

// ===================== HELPERS =====================
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

function formatTimestamp(seconds) {
    const sec = Math.max(0, Math.floor(seconds));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function parseTimestamp(ts) {
    const parts = String(ts).trim().replace(',', '.').split(':').map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0];
}

// ===================== KEYBOARD SHORTCUTS =====================
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'url-input') {
        e.preventDefault();
        fetchVideoInfo();
    }
});
