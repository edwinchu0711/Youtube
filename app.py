# app.py
from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
from threading import Thread
import time

app = Flask(__name__)

# 儲存下載狀態
downloads = {}

# yt-dlp 配置選項
def get_ydl_opts(output_path=None):
    opts = {
        'quiet': False,
        'no_warnings': False,
        'extract_flat': False,
        # 使用更多的 extractor 參數來避免被偵測
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls', 'dash']
            }
        },
        # 添加 headers 模擬真實瀏覽器
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        },
        # 添加 cookies（如果有的話）
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
    }
    
    if output_path:
        opts.update({
            'outtmpl': output_path,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        })
    
    return opts

def cleanup_old_files():
    """清理超過 1 小時的檔案"""
    downloads_dir = 'downloads'
    if not os.path.exists(downloads_dir):
        return
    
    current_time = time.time()
    for filename in os.listdir(downloads_dir):
        filepath = os.path.join(downloads_dir, filename)
        if os.path.isfile(filepath):
            if current_time - os.path.getmtime(filepath) > 3600:
                try:
                    os.remove(filepath)
                except:
                    pass

@app.route('/')
def home():
    return jsonify({
        "service": "YouTube Downloader API",
        "version": "2.0",
        "status": "running",
        "endpoints": {
            "/api/formats": "GET - 列出影片格式 (參數: url)",
            "/api/download": "POST - 下載影片 (參數: url, video_id, audio_id)",
            "/api/status/<task_id>": "GET - 查詢下載狀態",
            "/api/file/<task_id>": "GET - 下載檔案"
        }
    })

@app.route('/api/formats', methods=['GET'])
def list_formats():
    """列出所有可下載格式"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "請提供 URL 參數"}), 400
    
    try:
        ydl_opts = get_ydl_opts()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            format_list = []
            for f in formats:
                format_list.append({
                    "format_id": f.get('format_id', ''),
                    "resolution": f.get('resolution') or str(f.get('height', 'N/A')),
                    "fps": f.get('fps', ''),
                    "ext": f.get('ext', ''),
                    "filesize": f.get('filesize') or f.get('filesize_approx'),
                    "filesize_mb": round((f.get('filesize') or f.get('filesize_approx') or 0) / 1024 / 1024, 1),
                    "vcodec": f.get('vcodec', ''),
                    "acodec": f.get('acodec', ''),
                    "quality": f.get('quality', 0),
                })
            
            return jsonify({
                "title": info.get('title', ''),
                "duration": info.get('duration', 0),
                "thumbnail": info.get('thumbnail', ''),
                "uploader": info.get('uploader', ''),
                "formats": format_list
            })
    
    except Exception as e:
        error_msg = str(e)
        if "Sign in to confirm" in error_msg or "429" in error_msg:
            return jsonify({
                "error": "YouTube 偵測到機器人行為，請稍後再試或使用 Cookies",
                "details": error_msg,
                "solution": "請參考文件設定 cookies.txt"
            }), 429
        return jsonify({"error": error_msg}), 500

def download_task(task_id, url, video_id, audio_id):
    """背景下載任務"""
    try:
        downloads[task_id]['status'] = 'downloading'
        
        os.makedirs('downloads', exist_ok=True)
        
        output_path = f'downloads/{task_id}.%(ext)s'
        ydl_opts = get_ydl_opts(output_path)
        ydl_opts['format'] = f"{video_id}+{audio_id}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloads[task_id]['status'] = 'completed'
            downloads[task_id]['filename'] = f"{task_id}.mp4"
            downloads[task_id]['title'] = info.get('title', '')
    
    except Exception as e:
        downloads[task_id]['status'] = 'error'
        downloads[task_id]['error'] = str(e)

@app.route('/api/download', methods=['POST'])
def download_video():
    """開始下載影片"""
    data = request.get_json()
    
    url = data.get('url')
    video_id = data.get('video_id')
    audio_id = data.get('audio_id')
    
    if not all([url, video_id, audio_id]):
        return jsonify({"error": "請提供 url, video_id, audio_id"}), 400
    
    task_id = str(uuid.uuid4())
    
    downloads[task_id] = {
        'status': 'pending',
        'url': url,
        'video_id': video_id,
        'audio_id': audio_id,
        'created_at': time.time()
    }
    
    thread = Thread(target=download_task, args=(task_id, url, video_id, audio_id))
    thread.start()
    
    cleanup_old_files()
    
    return jsonify({
        "task_id": task_id,
        "status": "pending",
        "message": "下載任務已建立"
    })

@app.route('/api/status/<task_id>', methods=['GET'])
def check_status(task_id):
    """查詢下載狀態"""
    if task_id not in downloads:
        return jsonify({"error": "找不到該任務"}), 404
    
    return jsonify(downloads[task_id])

@app.route('/api/file/<task_id>', methods=['GET'])
def download_file(task_id):
    """下載檔案"""
    if task_id not in downloads:
        return jsonify({"error": "找不到該任務"}), 404
    
    if downloads[task_id]['status'] != 'completed':
        return jsonify({"error": "檔案尚未準備好"}), 400
    
    filename = downloads[task_id].get('filename')
    filepath = os.path.join('downloads', filename)
    
    if not os.path.exists(filepath):
        return jsonify({"error": "檔案不存在"}), 404
    
    return send_file(filepath, as_attachment=True, download_name=f"{downloads[task_id].get('title', 'video')}.mp4")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
