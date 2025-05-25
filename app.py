import os
import shutil
import uuid
from flask import Flask, request, jsonify, send_from_directory, after_this_request
import subprocess
import json

app = Flask(__name__)

TEMP_DOWNLOAD_BASE_DIR = "/tmp/yt_dlp_downloads"
COOKIE_FILE_PATH = os.environ.get('YT_DLP_COOKIE_FILE')

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
        command = ['yt-dlp', '-J', '--no-warnings']
        
        if COOKIE_FILE_PATH and os.path.exists(COOKIE_FILE_PATH):
            command.extend(['--cookies', COOKIE_FILE_PATH])
            app.logger.info(f"Attempting to use cookie file for get_info: {COOKIE_FILE_PATH}")
        else:
            app.logger.info("Cookie file not specified or not found for get_info. Proceeding without cookies.")
            
        command.append(video_url)
        
        app.logger.info(f"Running get_info command: {' '.join(command)}")
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        video_info = json.loads(process.stdout)
        return jsonify(video_info)

    except subprocess.CalledProcessError as e:
        app.logger.error(f"get_info yt-dlp failed. Return code: {e.returncode}\nStdout: {e.stdout}\nStderr: {e.stderr}")
        return jsonify({"error": "yt-dlp command failed for get_info", "returncode": e.returncode, "stderr": e.stderr, "stdout": e.stdout}), 500
    except json.JSONDecodeError as e:
        app.logger.error(f"get_info JSON parsing failed. Raw stdout: {getattr(process, 'stdout', 'N/A')}")
        return jsonify({"error": "Failed to parse yt-dlp JSON output for get_info", "details": str(e), "raw_stdout": getattr(process, 'stdout', 'N/A')}), 500
    except Exception as e:
        app.logger.error(f"get_info unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred during get_info", "details": str(e)}), 500

def handle_download(video_url, download_type):
    if not video_url:
        return jsonify({"error": "Missing 'url' parameter"}), 400

    download_id = str(uuid.uuid4())
    specific_download_dir = os.path.join(TEMP_DOWNLOAD_BASE_DIR, download_id)
    os.makedirs(specific_download_dir, exist_ok=True)

    output_template = os.path.join(specific_download_dir, "%(title)s - %(id)s.%(ext)s")
    
    command = ['yt-dlp', '--no-warnings', '--verbose'] # Added --verbose for more detailed logs

    if COOKIE_FILE_PATH and os.path.exists(COOKIE_FILE_PATH):
        command.extend(['--cookies', COOKIE_FILE_PATH])
        app.logger.info(f"Attempting to use cookie file for download: {COOKIE_FILE_PATH}")
    else:
        app.logger.info("Cookie file not specified or not found for download. Proceeding without cookies.")

    command.extend(['--output', output_template])

    if download_type == 'video':
        command.extend(['-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best'])
    elif download_type == 'audio':
        command.extend(['-x', '--audio-format', 'mp3', '--audio-quality', '0'])

    command.append(video_url)

    try:
        app.logger.info(f"Running download command: {' '.join(command)}")
        # We will not use check=True here to capture output even if yt-dlp has a non-zero exit due to cookie saving
        process = subprocess.run(command, capture_output=True, text=True) 
        
        app.logger.info(f"Download yt-dlp stdout: {process.stdout}")
        if process.stderr:
             app.logger.info(f"Download yt-dlp stderr: {process.stderr}") # Log stderr regardless of exit code

        # Check if files were downloaded, even if yt-dlp had a non-zero exit code due to cookie saving
        downloaded_files = os.listdir(specific_download_dir)
        if not downloaded_files:
            # If no files, then the download truly failed before file creation or yt-dlp error was critical
            if process.returncode != 0 : # yt-dlp indicated an error
                 shutil.rmtree(specific_download_dir)
                 return jsonify({"error": f"yt-dlp {download_type} download command truly failed or no file produced.", 
                                "returncode": process.returncode,
                                "stdout": process.stdout, 
                                "stderr": process.stderr,
                                "expected_dir": specific_download_dir}), 500
            else: # No files but yt-dlp exited cleanly (unlikely if no files, but handle)
                 shutil.rmtree(specific_download_dir)
                 return jsonify({"error": "yt-dlp ran but no file was found, though it exited cleanly.", 
                                "stdout": process.stdout, 
                                "stderr": process.stderr,
                                "expected_dir": specific_download_dir}), 500


        downloaded_filename = downloaded_files[0]
        app.logger.info(f"File to serve: {downloaded_filename} from {specific_download_dir}")

        # Check for the specific OSError related to saving cookies if yt-dlp had an error
        # This OSError typically happens at the very end of yt-dlp's execution.
        # If this is the *only* error, the download itself might have succeeded.
        if process.returncode != 0 and "Read-only file system" in process.stderr and COOKIE_FILE_PATH in process.stderr:
            app.logger.warning(f"yt-dlp exited with code {process.returncode} likely due to read-only cookie save attempt, but download may have succeeded.")
        elif process.returncode != 0: # Some other error from yt-dlp
            shutil.rmtree(specific_download_dir)
            return jsonify({
                "error": f"yt-dlp {download_type} download command failed with an unexpected error",
                "returncode": process.returncode,
                "stderr": process.stderr,
                "stdout": process.stdout
            }), 500


        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(specific_download_dir)
                app.logger.info(f"Successfully cleaned up {specific_download_dir}")
            except Exception as e:
                app.logger.error(f"Error during cleanup of {specific_download_dir}: {e}")
            return response

        return send_from_directory(directory=specific_download_dir, path=downloaded_filename, as_attachment=True)

    except Exception as e: # Catch other exceptions like issues with os.listdir, etc.
        app.logger.error(f"An unexpected error occurred in handle_download: {e}")
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
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)