import os
import shutil # For removing directories
import uuid # For unique temporary directory names
from flask import Flask, request, jsonify, send_from_directory, after_this_request
import subprocess
import json # For the /get_info endpoint

app = Flask(__name__)

# Base directory for temporary downloads within the container
TEMP_DOWNLOAD_BASE_DIR = "/tmp/yt_dlp_downloads"
# Get the cookie file path from the environment variable
COOKIE_FILE_PATH = os.environ.get('YT_DLP_COOKIE_FILE')

# Ensure the base temporary download directory exists when the app starts
if not os.path.exists(TEMP_DOWNLOAD_BASE_DIR):
    os.makedirs(TEMP_DOWNLOAD_BASE_DIR)

@app.route('/')
def home():
    return """
    <h1>yt-dlp on Render POC</h1>
    <p>Use the following endpoints:</p>
    <ul>
        <li><code>/get_info?url=YOUR_YOUTUBE_URL</code> - to get video metadata as JSON.</li>
        <li><code>/download_video?url=YOUR_YOUTUBE_URL</code> - to download the best quality video.</li>
        <li><code>/download_audio?url=YOUR_YOUTUBE_URL</code> - to download the best quality audio as MP3.</li>
    </ul>
    """

@app.route('/get_info', methods=['GET'])
def get_info():
    video_url = request.args.get('url')
    if not video_url:
        return jsonify({"error": "Missing 'url' parameter."}), 400
    
    try:
        command = ['yt-dlp', '-J', '--no-warnings'] # -J is --print-json
        
        if COOKIE_FILE_PATH and os.path.exists(COOKIE_FILE_PATH):
            command.extend(['--cookies', COOKIE_FILE_PATH])
            app.logger.info(f"Using cookie file for get_info: {COOKIE_FILE_PATH}")
        else:
            app.logger.info("Cookie file not specified or not found for get_info. Proceeding without cookies.")
            
        command.append(video_url)
        
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        video_info = json.loads(process.stdout)
        return jsonify(video_info)
    except subprocess.CalledProcessError as e:
        return jsonify({"error": "yt-dlp command failed", "returncode": e.returncode, "stderr": e.stderr, "stdout": e.stdout}), 500
    except json.JSONDecodeError as e:
        # Use getattr to safely access process.stdout, as process might not be defined if run fails earlier
        return jsonify({"error": "Failed to parse yt-dlp JSON output", "details": str(e), "raw_stdout": getattr(process, 'stdout', 'N/A')}), 500
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500

def handle_download(video_url, download_type):
    if not video_url:
        return jsonify({"error": "Missing 'url' parameter"}), 400

    download_id = str(uuid.uuid4())
    specific_download_dir = os.path.join(TEMP_DOWNLOAD_BASE_DIR, download_id)
    os.makedirs(specific_download_dir, exist_ok=True)

    # CORRECTED TYPO HERE (was specific_download__dir)
    output_template = os.path.join(specific_download_dir, "%(title)s - %(id)s.%(ext)s") 
    
    command = ['yt-dlp', '--no-warnings']

    # Add cookie command if cookie file path is set and file exists
    if COOKIE_FILE_PATH and os.path.exists(COOKIE_FILE_PATH):
        command.extend(['--cookies', COOKIE_FILE_PATH])
        app.logger.info(f"Using cookie file for download: {COOKIE_FILE_PATH}")
    else:
        app.logger.info("Cookie file not specified or not found for download. Proceeding without cookies.")

    command.extend(['--output', output_template]) # Add output option

    if download_type == 'video':
        command.extend(['-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best'])
    elif download_type == 'audio':
        command.extend(['-x', '--audio-format', 'mp3', '--audio-quality', '0'])

    command.append(video_url)

    try:
        app.logger.info(f"Running command: {' '.join(command)}")
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        app.logger.info(f"yt-dlp stdout: {process.stdout}")
        if process.stderr: # Log stderr even on success, as yt-dlp might print info there
            app.logger.info(f"yt-dlp stderr: {process.stderr}")


        downloaded_files = os.listdir(specific_download_dir)
        if not downloaded_files:
            shutil.rmtree(specific_download_dir)
            return jsonify({"error": "yt-dlp ran but no file was found in the temporary directory.", 
                            "stdout": process.stdout, 
                            "stderr": process.stderr,
                            "expected_dir": specific_download_dir}), 500
        
        downloaded_filename = downloaded_files[0]
        app.logger.info(f"File to serve: {downloaded_filename} from {specific_download_dir}")

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(specific_download_dir)
                app.logger.info(f"Successfully cleaned up {specific_download_dir}")
            except Exception as e:
                app.logger.error(f"Error during cleanup of {specific_download_dir}: {e}")
            return response

        return send_from_directory(directory=specific_download_dir, path=downloaded_filename, as_attachment=True)

    except subprocess.CalledProcessError as e:
        app.logger.error(f"yt-dlp failed. Return code: {e.returncode}\nStdout: {e.stdout}\nStderr: {e.stderr}")
        shutil.rmtree(specific_download_dir) # Clean up
        return jsonify({
            "error": f"yt-dlp {download_type} download command failed",
            "returncode": e.returncode,
            "stderr": e.stderr,
            "stdout": e.stdout
        }), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}")
        shutil.rmtree(specific_download_dir) # Clean up
        return jsonify({"error": f"An unexpected error occurred during {download_type} download", "details": str(e)}), 500

@app.route('/download_video', methods=['GET'])
def download_video_route():
    video_url = request.args.get('url')
    return handle_download(video_url, 'video')

@app.route('/download_audio', methods=['GET'])
def download_audio_route():
    video_url = request.args.get('url')
    return handle_download(video_url, 'audio')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    # Enable Flask development server debugging if FLASK_DEBUG env var is set to 'true'
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)