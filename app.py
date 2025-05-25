import os
from flask import Flask, request, jsonify
import subprocess
import json

app = Flask(__name__)

@app.route('/')
def home():
    return "Welcome! Use /get_info?url=YOUR_YOUTUBE_URL to get video info."

@app.route('/get_info', methods=['GET'])
def get_info():
    video_url = request.args.get('url')
    if not video_url:
        return jsonify({"error": "Missing 'url' parameter. Use like: /get_info?url=YOUR_YOUTUBE_URL"}), 400

    try:
        # Run yt-dlp to get video information as JSON
        # -J is short for --print-json
        # --no-warnings keeps the output clean if it's just JSON
        # We explicitly use the yt-dlp installed via pip in our Docker image
        command = ['yt-dlp', '-J', '--no-warnings', video_url]

        process = subprocess.run(
            command,
            capture_output=True,
            text=True, # Decodes stdout/stderr as string
            check=True  # Raises CalledProcessError for non-zero exit codes
        )

        video_info = json.loads(process.stdout)
        return jsonify(video_info)

    except subprocess.CalledProcessError as e:
        # If yt-dlp returns a non-zero exit code
        return jsonify({
            "error": "yt-dlp command failed",
            "returncode": e.returncode,
            "stderr": e.stderr,
            "stdout": e.stdout # yt-dlp might print partial info or errors to stdout too
        }), 500
    except json.JSONDecodeError as e:
        # If yt-dlp output was not valid JSON
        return jsonify({
            "error": "Failed to parse yt-dlp JSON output",
            "details": str(e),
            "raw_stdout": process.stdout # Show what yt-dlp actually outputted
        }), 500
    except Exception as e:
        # Catch any other unexpected errors
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500

if __name__ == '__main__':
    # Render provides the PORT environment variable
    port = int(os.environ.get('PORT', 8080)) 
    # Listen on 0.0.0.0 to be accessible from outside the container
    app.run(host='0.0.0.0', port=port)