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

def cleanup_old_files():
    """清理超過 1 小時的檔案"""
    downloads_dir = 'downloads'
    if not os.path.exists(downloads_dir):
        return
    
    current_time = time.time()
    for filename in os.listdir(downloads_dir):
        filepath = os.path.join(downloads_dir, filename)
        if os.path.isfile(filepath):
            if current_time - os.path.getmtime(filepath) > 3600:  # 1 小時
                os.remove(filepath)

@app.route('/')
def home():
    return jsonify({
        "service": "YouTube Downloader API",
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
        with yt_dlp.YoutubeDL() as ydl:
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
                })
            
            return jsonify({
                "title": info.get('title', ''),
                "duration": info.get('duration', 0),
                "formats": format_list
            })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def download_task(task_id, url, video_id, audio_id):
    """背景下載任務"""
    try:
        downloads[task_id]['status'] = 'downloading'
        
        # 確保下載目錄存在
        os.makedirs('downloads', exist_ok=True)
        
        ydl_opts = {
            'outtmpl': f'downloads/{task_id}.%(ext)s',
            'merge_output_format': 'mp4',
            'format': f"{video_id}+{audio_id}",
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        }
        
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
    
    # 生成任務 ID
    task_id = str(uuid.uuid4())
    
    # 初始化下載狀態
    downloads[task_id] = {
        'status': 'pending',
        'url': url,
        'video_id': video_id,
        'audio_id': audio_id
    }
    
    # 啟動背景下載
    thread = Thread(target=download_task, args=(task_id, url, video_id, audio_id))
    thread.start()
    
    # 清理舊檔案
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
    
    return send_file(filepath, as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)