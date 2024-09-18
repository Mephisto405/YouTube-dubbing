import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import yt_dlp as youtube_dl
import speech_recognition as sr
from googletrans import Translator
from gtts import gTTS
import os
from pydub import AudioSegment
from pydub.utils import make_chunks

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

def update_progress(step, progress):
    socketio.emit('progress_update', {'step': step, 'progress': progress})
    socketio.sleep(0)

def yt_progress_hook(d):
    if d['status'] == 'downloading':
        progress = float(d['downloaded_bytes'] / d['total_bytes'] * 100) if 'total_bytes' in d else 0
        update_progress("유튜브 동영상 다운로드 중", progress)
    elif d['status'] == 'finished':
        update_progress("유튜브 동영상 다운로드 완료", 100)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    youtube_url = request.form['youtube_url']
    
    try:
        # 1. 유튜브 동영상 다운로드
        update_progress("유튜브 동영상 다운로드 준비 중", 0)
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'outtmpl': 'audio.%(ext)s',
            'progress_hooks': [yt_progress_hook],
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        
        # 2. 음성 인식 (STT)
        update_progress("음성 인식 준비 중", 0)
        recognizer = sr.Recognizer()
        audio_file = AudioSegment.from_wav("audio.wav")
        chunk_length_ms = 60000  # 1분 단위로 청크 생성
        chunks = make_chunks(audio_file, chunk_length_ms)
        
        full_text = ""
        for i, chunk in enumerate(chunks):
            progress = (i + 1) / len(chunks) * 100
            update_progress(f"음성 인식 중 ({i+1}/{len(chunks)})", progress)
            chunk.export(f"chunk{i}.wav", format="wav")
            with sr.AudioFile(f"chunk{i}.wav") as source:
                audio = recognizer.record(source)
            try:
                text = recognizer.recognize_google(audio)
                full_text += text + " "
            except sr.RequestError as e:
                return jsonify({'status': 'error', 'message': f"Could not request results from Google Speech Recognition service; {e}"})
            except sr.UnknownValueError:
                print(f"Google Speech Recognition could not understand audio in chunk {i}")
            os.remove(f"chunk{i}.wav")
        
        # 3. 번역
        update_progress("텍스트 번역 중", 0)
        translator = Translator()
        translated_text = translator.translate(full_text, dest='ko').text
        update_progress("텍스트 번역 중", 100)
        
        # 4. TTS
        update_progress("음성 생성 중", 0)
        tts = gTTS(text=translated_text, lang='ko')
        tts.save('dubbed_audio.mp3')
        update_progress("음성 생성 중", 100)
        
        update_progress("처리 완료", 100)
        return jsonify({'status': 'success', 'audio_file': 'dubbed_audio.mp3'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        # 임시 파일 삭제
        if os.path.exists('audio.wav'):
            os.remove('audio.wav')

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_file(filename, mimetype='audio/mpeg')

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)