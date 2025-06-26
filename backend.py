from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import os
import uuid
from datetime import datetime, timedelta
import shutil
import logging
from pathlib import Path
import threading

# Configuration du logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Définition de la fonction sanitize_filename au niveau global
def sanitize_filename(filename):
    # Remplacer les caractères interdits dans les noms de fichiers Windows
    forbidden_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in forbidden_chars:
        filename = filename.replace(char, '_')
    return filename

app = Flask(__name__)
CORS(app)

# Utiliser directement le dossier Vidéos de l'utilisateur sans sous-dossier
DOWNLOAD_FOLDER = Path(os.path.expanduser('~/Videos'))
if not DOWNLOAD_FOLDER.exists():
    DOWNLOAD_FOLDER.mkdir(parents=True)

# Configuration globale pour yt-dlp
# Configuration globale pour yt-dlp
ydl_opts = {
    'format': 'bestvideo[height<=1080]+bestaudio/best',
    'merge_output_format': 'mp4',
    'quiet': False,
    'no_warnings': False,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_color': True,
    'noprogress': True,
    'allow_unplayable_formats': False,  # Changé à False pour éviter les problèmes de formats
    'age_limit': 99,  # Pour contourner les restrictions d'âge
    'extractor_args': {
        'youtube': {
            'player_client': ['android'],
            'player_skip': ['webpage', 'config', 'js']
        },
        'instagram': {
            'skip_webpage': False,  # Nécessaire pour Instagram
            'compatible_formats': True  # Pour assurer la compatibilité des formats
        },
        'tiktok': {
            'api_hostname': 'api22-normal-c-useast1a.tiktokv.com',  # API TikTok plus stable
            'app_version': '20.4.3',
            'device_id': '7166960629302428165'
        }
    },
    'postprocessors': [{
        'key': 'FFmpegVideoConvertor',
        'preferedformat': 'mp4'  # Correction: 'preferredformat' -> 'preferedformat'
    }]
}

# Ajouter un dictionnaire pour suivre l'état des téléchargements
download_status = {}

def download_in_background(url, download_id):
    try:
        # Ajouter un log pour le débogage
        logger.info(f"Options de téléchargement pour `{url}:` {ydl_opts}")
        
        # Pas de sous-dossier, télécharger directement dans le dossier Vidéos
        # Copier les options et modifier le chemin de sortie
        temp_opts = ydl_opts.copy()
        temp_opts['outtmpl'] = str(DOWNLOAD_FOLDER / '%(title)s.%(ext)s')
        
        # Ajuster les options en fonction de la plateforme
        if 'instagram.com' in url:
            # Options spécifiques pour Instagram
            temp_opts['format'] = 'best'
            temp_opts['add_header'] = [
                ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            ]
        elif 'tiktok.com' in url:
            # Options spécifiques pour TikTok
            temp_opts['format'] = 'best'
        elif 'facebook.com' in url or 'fb.com' in url or 'fb.watch' in url:
            # Options spécifiques pour Facebook
            temp_opts['format'] = 'best'
        elif 'twitter.com' in url or 'x.com' in url:
            # Options spécifiques pour Twitter/X
            temp_opts['format'] = 'best'
        
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'file_name': None,
            'error': None
        }
        
        with yt_dlp.YoutubeDL(temp_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if info:
                # Obtenir le nom du fichier à partir des informations
                # La fonction sanitize_filename est maintenant définie globalement
                
                # Puis modifiez la partie qui gère le téléchargement
                if 'title' in info and info['title']:
                    # Sanitize le titre pour éviter les caractères interdits dans les noms de fichiers
                    sanitized_title = sanitize_filename(info['title'])
                    file_name = f"{sanitized_title}.mp4"
                    file_path = DOWNLOAD_FOLDER / file_name
                    
                    # Vérifier si le fichier existe
                    if file_path.exists():
                        download_status[download_id] = {
                            'status': 'completed',
                            'progress': 100,
                            'file_name': file_name,
                            'file_path': str(file_path),
                            'error': None
                        }
                        logger.info(f"Téléchargement terminé: {file_path}")
                    else:
                        # Chercher des fichiers similaires (peut-être avec .part ou autre extension)
                        similar_files = list(DOWNLOAD_FOLDER.glob(f"{info['title']}*"))
                        if similar_files:
                            file_name = similar_files[0].name
                            download_status[download_id] = {
                                'status': 'completed',
                                'progress': 100,
                                'file_name': file_name,
                                'file_path': str(similar_files[0]),
                                'error': None
                            }
                            logger.info(f"Téléchargement terminé (fichier similaire trouvé): {similar_files[0]}")
                        else:
                            # Vérifier si un fichier a été téléchargé avec un nom différent
                            # (cela peut arriver avec certaines plateformes)
                            recent_files = sorted(
                                [f for f in DOWNLOAD_FOLDER.glob('*.mp4') if f.stat().st_mtime > (datetime.now() - timedelta(minutes=1)).timestamp()],
                                key=lambda x: x.stat().st_mtime,
                                reverse=True
                            )
                            
                            if recent_files:
                                file_name = recent_files[0].name
                                download_status[download_id] = {
                                    'status': 'completed',
                                    'progress': 100,
                                    'file_name': file_name,
                                    'file_path': str(recent_files[0]),
                                    'error': None
                                }
                                logger.info(f"Téléchargement terminé (fichier récent trouvé): {recent_files[0]}")
                            else:
                                download_status[download_id] = {
                                    'status': 'error',
                                    'progress': 0,
                                    'file_name': None,
                                    'error': 'No file downloaded'
                                }
                                logger.error(f"Aucun fichier téléchargé pour {url}")
                else:
                    download_status[download_id] = {
                        'status': 'error',
                        'progress': 0,
                        'file_name': None,
                        'error': 'No title found in video info'
                    }
                    logger.error(f"Pas de titre trouvé pour {url}")
            else:
                download_status[download_id] = {
                    'status': 'error',
                    'progress': 0,
                    'file_name': None,
                    'error': 'Failed to extract video info'
                }
    except Exception as e:
        logger.error(f"Exception lors du téléchargement de `{url}:` {str(e)}")
        download_status[download_id] = {
            'status': 'error',
            'progress': 0,
            'file_name': None,
            'error': str(e)
        }

@app.route('/download', methods=['POST', 'OPTIONS'])
def download_video():
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.get_json()
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        logger.info(f"\nDémarrage du téléchargement pour : {url}")
        
        # Créer un ID unique pour ce téléchargement
        download_id = str(uuid.uuid4())
        
        # Démarrer le téléchargement en arrière-plan
        thread = threading.Thread(target=download_in_background, args=(url, download_id))
        thread.daemon = True
        thread.start()
        
        # Renvoyer immédiatement l'ID de téléchargement
        return jsonify({
            'status': 'started',
            'download_id': download_id
        })

    except Exception as e:
        logger.error(f"Erreur générale : {str(e)}")
        return jsonify({'error': str(e)}), 500

# Assurez-vous que cette route existe et fonctionne correctement
@app.route('/download/status/<download_id>', methods=['GET'])
def get_download_status(download_id):
    if download_id in download_status:
        return jsonify(download_status[download_id])
    return jsonify({'status': 'not_found'}), 404

@app.route('/download/<download_id>/<file_name>', methods=['GET'])
def get_downloaded_file(download_id, file_name):
    # Sanitize le nom de fichier reçu de l'URL, bien que nous utilisions le chemin stocké en priorité.
    file_name = sanitize_filename(file_name)
    
    status = download_status.get(download_id)
    if status and status['status'] == 'completed':
        # Obtenir le chemin du fichier depuis le statut, c'est la méthode la plus fiable
        file_path_str = status.get('file_path')
        
        # Logique de secours pour trouver le fichier si file_path n'est pas dans le statut
        if not file_path_str:
            file_path_str = str(DOWNLOAD_FOLDER / file_name)
            if not os.path.exists(file_path_str):
                for ext in ['.part', '.mp4', '.m4a', '.mp3', '.webm']:
                    test_path = str(DOWNLOAD_FOLDER / (os.path.splitext(file_name)[0] + ext))
                    if os.path.exists(test_path):
                        file_path_str = test_path
                        logger.info(f"Fichier trouvé avec extension alternative: {file_path_str}")
                        break
        
        file_path = Path(file_path_str)

        if file_path.exists():
            logger.info(f"Début de l'envoi en streaming pour le fichier : {file_path}")

            def generate():
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)  # Envoyer par blocs de 8KB
                        if not chunk:
                            break
                        yield chunk
            
            mimetype = 'video/mp4'
            if file_path.suffix.lower() in ['.m4a', '.mp3']:
                mimetype = 'audio/mp4'
            
            res = Response(stream_with_context(generate()), mimetype=mimetype)
            res.headers['Content-Disposition'] = f'attachment; filename="{file_path.name}"'
            res.headers['Content-Length'] = os.path.getsize(file_path)
            return res
    
    return jsonify({'error': 'File not found or download not complete'}), 404

@app.route('/formats/<video_id>', methods=['GET'])
def get_formats(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            return jsonify([{
                'format_id': f.get('format_id'),
                'ext': f.get('ext'),
                'resolution': f.get('resolution'),
                'filesize': f.get('filesize'),
                'format': f.get('format')
            } for f in formats])
        except Exception as e:
            return jsonify({'error': str(e)}), 500

def cleanup_old_downloads():
    """Nettoie les anciens téléchargements du dossier Videos"""
    logger.info("Nettoyage des anciens téléchargements désactivé car nous utilisons le dossier Videos standard")
    # Cette fonction est vide car nous utilisons maintenant le dossier Videos standard
    # et nous ne voulons pas supprimer automatiquement les fichiers de l'utilisateur
    pass

if __name__ == '__main__':
    # Nettoyer les anciens téléchargements au démarrage
    cleanup_old_downloads()
    app.run(debug=False, port=5000)
