# app.py - 無需 Cookies 的版本
from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
from threading import Thread
import time
import random

app = Flask(__name__)

downloads = {}

# 多個 User-Agent 輪換
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]

def get_ydl_opts(output_path=None, use_format=None):
    """動態配置 yt-dlp 選項"""
    
    # 隨機選擇 User-Agent
    user_agent = random.choice(USER_AGENTS)
    
    opts = {
        'quiet': True,
        'no_warnings': True,
        # 使用 Android 客戶端（最不容易被擋）
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
                'skip': ['hls', 'dash'],
            }
        },
        # 隨機 User-Agent
        'http_headers': {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        },
        # 添加延遲避免被偵測
        'sleep_interval': 1,
        'max_sleep_interval': 3,
        # 重試機制
        'retries': 3,
        'fragment_retries': 3,
        # 使用 IPv4（更穩定）
        'source_address': '0.0.0.0',
    }
    
    # 如果有 cookies.txt 就使用
    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'
        print("✅ 使用 Cookies 認證")
    else:
        print("⚠️ 未使用 Cookies（可能會有限制）")
    
    if output_path:
        opts.update({
            'outtmpl': output_path,
            'merge_output_format': 'mp4',
        })
        
        if use_format:
            opts['format'] = use_format
    
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
                    print(f"🗑️ 清理舊檔案: {filename}")
                except:
                    pass

@app.route('/')
def home():
    has_cookies = os.path.exists('cookies.txt')
    return jsonify({
        "service": "YouTube Downloader API",
        "version": "3.0",
        "status": "running",
        "authentication": "cookies" if has_cookies else "none",
        "cookie_status": "✅ Active" if has_cookies else "⚠️ Not configured",
        "endpoints": {
            "/api/formats": "GET - 列出影片格式 (參數: url)",
            "/api/download": "POST - 下載影片 (參數: url, format_id 或 video_id+audio_id)",
            "/api/status/<task_id>": "GET - 查詢下載狀態",
            "/api/file/<task_id>": "GET - 下載檔案",
            "/api/health": "GET - 健康檢查"
        }
    })

@app.route('/api/health')
def health_check():
    """健康檢查端點"""
    return jsonify({
        "status": "healthy",
        "cookies": os.path.exists('cookies.txt'),
        "downloads_count": len(downloads),
        "timestamp": time.time()
    })

@app.route('/api/formats', methods=['GET'])
def list_formats():
    """列出所有可下載格式"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"success": False, "error": "請提供 URL 參數"}), 400
    
    # 添加隨機延遲避免被偵測
    time.sleep(random.uniform(0.5, 1.5))
    
    try:
        ydl_opts = get_ydl_opts()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"📥 提取影片資訊: {url}")
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            format_list = []
            seen_formats = set()
            
            for f in formats:
                format_id = f.get('format_id', '')
                
                # 避免重複格式
                format_key = f"{format_id}_{f.get('ext', '')}"
                if format_key in seen_formats:
                    continue
                seen_formats.add(format_key)
                
                # 過濾掉不完整的格式
                if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
                    continue
                
                format_info = {
                    "format_id": format_id,
                    "resolution": f.get('resolution') or f"{f.get('height', 'N/A')}p",
                    "fps": f.get('fps', ''),
                    "ext": f.get('ext', ''),
                    "filesize": f.get('filesize') or f.get('filesize_approx'),
                    "filesize_mb": round((f.get('filesize') or f.get('filesize_approx') or 0) / 1024 / 1024, 1),
                    "vcodec": f.get('vcodec', ''),
                    "acodec": f.get('acodec', ''),
                    "quality": f.get('quality', 0),
                    "format_note": f.get('format_note', ''),
                    "tbr": f.get('tbr', 0),  # 總位元率
                }
                format_list.append(format_info)
            
            # 按品質排序
            format_list.sort(key=lambda x: (
                int(x['resolution'].replace('p', '').replace('N/A', '0')),
                x['tbr']
            ), reverse=True)
            
            print(f"✅ 成功提取 {len(format_list)} 個格式")
            
            return jsonify({
                "success": True,
                "title": info.get('title', ''),
                "duration": info.get('duration', 0),
                "thumbnail": info.get('thumbnail', ''),
                "uploader": info.get('uploader', ''),
                "view_count": info.get('view_count', 0),
                "upload_date": info.get('upload_date', ''),
                "formats": format_list,
                "formats_count": len(format_list)
            })
    
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 錯誤: {error_msg}")
        
        # 判斷錯誤類型
        if "Sign in to confirm" in error_msg or "429" in error_msg:
            return jsonify({
                "success": False,
                "error": "YouTube 偵測到機器人行為",
                "error_type": "rate_limit",
                "details": error_msg,
                "solution": "需要設定 Cookies 或稍後再試",
                "retry_after": 300  # 建議 5 分鐘後重試
            }), 429
        
        elif "Video unavailable" in error_msg:
            return jsonify({
                "success": False,
                "error": "影片無法使用",
                "error_type": "unavailable",
                "details": "影片可能已被刪除、設為私人或地區限制"
            }), 404
        
        else:
            return jsonify({
                "success": False,
                "error": "提取影片資訊失敗",
                "error_type": "unknown",
                "details": error_msg
            }), 500

def download_task(task_id, url, format_spec):
    """背景下載任務"""
    try:
        downloads[task_id]['status'] = 'downloading'
        downloads[task_id]['progress'] = 0
        
        os.makedirs('downloads', exist_ok=True)
        
        output_path = f'downloads/{task_id}.%(ext)s'
        
        # 進度回調
        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    percent = d.get('_percent_str', '0%').replace('%', '')
                    downloads[task_id]['progress'] = float(percent)
                except:
                    pass
            elif d['status'] == 'finished':
                downloads[task_id]['progress'] = 100
        
        ydl_opts = get_ydl_opts(output_path, format_spec)
        ydl_opts['progress_hooks'] = [progress_hook]
        
        print(f"⬇️ 開始下載: {url}, 格式: {format_spec}")
        
        # 添加延遲
        time.sleep(random.uniform(1, 2))
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # 找到實際下載的檔案
            downloaded_file = None
            for file in os.listdir('downloads'):
                if file.startswith(task_id):
                    downloaded_file = file
                    break
            
            if downloaded_file:
                file_size = os.path.getsize(f'downloads/{downloaded_file}')
                downloads[task_id]['status'] = 'completed'
                downloads[task_id]['filename'] = downloaded_file
                downloads[task_id]['title'] = info.get('title', '')
                downloads[task_id]['filesize'] = file_size
                downloads[task_id]['progress'] = 100
                print(f"✅ 下載完成: {downloaded_file} ({file_size / 1024 / 1024:.2f} MB)")
            else:
                raise Exception("找不到下載的檔案")
    
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 下載錯誤: {error_msg}")
        downloads[task_id]['status'] = 'error'
        downloads[task_id]['error'] = error_msg

@app.route('/api/download', methods=['POST'])
def download_video():
    """開始下載影片"""
    data = request.get_json()
    
    url = data.get('url')
    format_id = data.get('format_id')
    video_id = data.get('video_id')
    audio_id = data.get('audio_id')
    
    if not url:
        return jsonify({"success": False, "error": "請提供 url"}), 400
    
    # 決定格式字串
    if format_id:
        format_spec = format_id
    elif video_id and audio_id:
        format_spec = f"{video_id}+{audio_id}"
    elif video_id:
        format_spec = video_id
    else:
        format_spec = "best"
    
    task_id = str(uuid.uuid4())
    
    downloads[task_id] = {
        'status': 'pending',
        'url': url,
        'format': format_spec,
        'progress': 0,
        'created_at': time.time()
    }
    
    thread = Thread(target=download_task, args=(task_id, url, format_spec))
    thread.daemon = True
    thread.start()
    
    # 清理舊檔案
    cleanup_old_files()
    
    return jsonify({
        "success": True,
        "task_id": task_id,
        "status": "pending",
        "message": "下載任務已建立"
    })

@app.route('/api/status/<task_id>', methods=['GET'])
def check_status(task_id):
    """查詢下載狀態"""
    if task_id not in downloads:
        return jsonify({"success": False, "error": "找不到該任務"}), 404
    
    return jsonify({
        "success": True,
        **downloads[task_id]
    })

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
    
    title = downloads[task_id].get('title', 'video')
    # 清理檔名
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_', '.')).strip()[:100]
    ext = os.path.splitext(filename)[1]
    
    return send_file(
        filepath, 
        as_attachment=True, 
        download_name=f"{safe_title}{ext}"
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
