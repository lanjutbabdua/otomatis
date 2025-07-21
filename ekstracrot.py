import os
import requests
import json
import datetime
import time
import random
import re
import markdown
import google.generativeai as genai # Tetap diimpor tapi tidak dipanggil
import unicodedata
from urllib.parse import quote_plus

# --- Konfigurasi ---
API_SOURCE_URL = "https://kisah69.blog/wp-json/wp/v2/posts"
# WP_TARGET_API_URL yang sudah benar untuk ekstracrot.wordpress.com
WP_TARGET_API_URL = "https://public-api.wordpress.com/rest/v1.1/sites/137050535/posts"
STATE_FILE = 'artikel_terbit.json'
RANDOM_IMAGES_FILE = 'random_images.json'

# --- Konfigurasi Gemini AI (DINONAKTIFKAN SEMENTARA) ---
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_TITLE")
# if not GEMINI_API_KEY:
#     raise ValueError("GEMINI_API_KEY_TITLE environment variable not set. Please set it in your GitHub Secrets or local environment.")
# genai.configure(api_key=GEMINI_API_KEY)
# gemini_model_content = genai.GenerativeModel("gemini-1.5-flash")
# gemini_model_title = genai.GenerativeModel("gemini-1.5-flash")

# --- Konfigurasi Kredensial WordPress Target ---
WP_USERNAME = os.getenv('WP_USERNAME')
WP_APP_PASSWORD = os.getenv('WP_APP_PASSWORD')
if not WP_USERNAME or not WP_APP_PASSWORD:
    raise ValueError("WP_USERNAME and WP_APP_PASSWORD environment variables not set for target WordPress. Please set them in GitHub Secrets.")

# --- Penggantian Kata Khusus ---
REPLACEMENT_MAP = {
    "memek": "serambi lempit",
    "kontol": "rudal",
    "ngentot": "menggenjot",
    "vagina": "serambi lempit",
    "penis": "rudal",
    "seks": "bercinta",
    "mani": "kenikmatan",
    "sex": "bercinta"
}

# === Utilitas ===
def extract_first_image_url(html_content):
    match = re.search(r'<img[^>]+src="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def strip_html_and_divs(html):
    html_with_newlines = re.sub(r'</p>', r'\n\n', html, flags=re.IGNORECASE)
    html_no_images = re.sub(r'<img[^>]*>', '', html_with_newlines)
    html_no_divs = re.sub(r'</?div[^>]*>', '', html_no_images, flags=re.IGNORECASE)
    clean_text = re.sub('<[^<]+?>', '', html_no_divs)
    clean_text = re.sub(r'\n{3,}', r'\n\n', clean_text).strip()
    return clean_text

def remove_anchor_tags(html_content):
    return re.sub(r'<a[^>]*>(.*?)<\/a>', r'\1', html_content)

def sanitize_filename(title):
    clean_title = re.sub(r'[^\w\s-]', '', title).strip().lower()
    return re.sub(r'[-\s]+', '-', clean_title)

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = str(value)
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('utf-8')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'[-\s]+', '-', value)

def replace_custom_words(text):
    processed_text = text
    sorted_replacements = sorted(REPLACEMENT_MAP.items(), key=lambda item: len(item[0]), reverse=True)
    for old_word, new_word in sorted_replacements:
        pattern = re.compile(re.escape(old_word), re.IGNORECASE)
        processed_text = pattern.sub(new_word, processed_text)
    return processed_text

# Fungsi edit_title_with_gemini dinonaktifkan
def edit_title_with_gemini(original_title):
    print(f"⚠️ Gemini AI untuk pengeditan judul dinonaktifkan. Menggunakan judul asli.")
    return original_title

# Fungsi edit_first_300_words_with_gemini dinonaktifkan
def edit_first_300_words_with_gemini(post_id, post_title, full_text_content):
    print(f"⚠️ Gemini AI untuk pengeditan konten (300 kata pertama) dinonaktifkan. Menggunakan konten asli.")
    return full_text_content

# --- Fungsi untuk memuat dan menyimpan status postingan yang sudah diterbitkan ---
def load_published_posts_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print(f"Warning: {STATE_FILE} is corrupted or empty. Starting with an empty published posts list.")
                return set()
    return set()

def save_published_posts_state(published_ids):
    with open(STATE_FILE, 'w') as f:
        json.dump(list(published_ids), f)

def load_image_urls(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            try:
                urls = json.load(f)
                if isinstance(urls, list) and all(isinstance(url, str) for url in urls):
                    print(f"✅ Berhasil memuat {len(urls)} URL gambar dari '{file_path}'.")
                    return urls
                else:
                    print(f"❌ Error: Konten '{file_path}' bukan daftar string URL yang valid.")
                    return []
            except json.JSONDecodeError:
                print(f"❌ Error: Gagal mengurai JSON dari '{file_path}'. Pastikan formatnya benar.")
                return []
    else:
        print(f"⚠️ Peringatan: File '{file_path}' tidak ditemukan. Tidak ada gambar acak yang akan ditambahkan.")
        return []

def get_random_image_url(image_urls):
    if image_urls:
        return random.choice(image_urls)
    return None

# --- Fungsi untuk Mengirim Post ke WordPress Target ---
def publish_post_to_wordpress(wp_api_url, title, content_html, username, app_password, random_image_url=None, post_status='publish'):
    print(f"🚀 Menerbitkan '{title}' ke WordPress: {wp_api_url}...")
    final_content_for_wp = content_html
    if random_image_url:
        image_html = f'<p><img src="{random_image_url}" alt="{title}" style="max-width: 100%; height: auto; display: block; margin: 0 auto;"></p>'
        final_content_for_wp = image_html + "\n\n" + content_html
        print(f"🖼️ Gambar acak '{random_image_url}' ditambahkan ke artikel.")
    
    # --- Debugging: Cek Kredensial ---
    if not username or not app_password:
        print("❌ ERROR: WP_USERNAME atau WP_APP_PASSWORD tidak diatur dengan benar untuk proses publikasi.")
        return None

    post_data = {
        'title': title,
        'content': final_content_for_wp,
        'status': post_status,
        # Menambahkan slug secara eksplisit.
        # WordPress.com biasanya membuat slug dari judul, tapi ini bisa membantu debug.
        'slug': slugify(title)
    }
    
    auth = requests.auth.HTTPBasicAuth(username, app_password)
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json' # Minta respons dalam format JSON secara eksplisit
    }

    print("\n--- Debugging Detail Permintaan POST ---")
    print(f"URL Target: {wp_api_url}")
    print(f"Header: {json.dumps(headers, indent=2)}")
    # Masking app_password untuk keamanan dalam log
    print(f"Kredensial Auth: Username='{username}', App Password='{'*' * len(app_password) if app_password else 'N/A'}' (disensor)")
    # Menampilkan sebagian kecil konten jika terlalu panjang
    content_preview = post_data['content'][:500] + '...' if len(post_data['content']) > 500 else post_data['content']
    print(f"Payload JSON (sebagian): {json.dumps({'title': post_data['title'], 'status': post_data['status'], 'slug': post_data['slug'], 'content_preview': content_preview}, indent=2)}")
    print("---------------------------------------\n")

    try:
        response = requests.post(wp_api_url, headers=headers, json=post_data, auth=auth)
        response.raise_for_status() # Ini akan memicu HTTPError untuk kode status 4xx/5xx
        result = response.json()
        print(f"✅ Artikel '{title}' berhasil diterbitkan ke WordPress! URL: {result.get('URL')}")
        return result
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error saat memposting ke WordPress: {e}")
        # Mencetak respons penuh dari server untuk analisis lebih lanjut
        print(f"Respons server: {response.text}")
        # Coba parsing respons untuk error code/message spesifik dari WordPress.com
        if response.text:
            try:
                error_details = response.json()
                if 'code' in error_details:
                    print(f"Kode Error WordPress: {error_details.get('code')}")
                if 'message' in error_details:
                    print(f"Pesan Error WordPress: {error_details.get('message')}")
            except json.JSONDecodeError:
                pass # Jika respons bukan JSON, abaikan
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Terjadi kesalahan koneksi ke WordPress API: {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ Gagal mendekode JSON dari respons WordPress: {response.text}")
        return None
    except Exception as e:
        print(f"❌ Terjadi kesalahan tak terduga saat memposting ke WordPress: {e}")
        return None

# === Ambil semua postingan dari WordPress Self-Hosted REST API (SUMBER) ===
def fetch_raw_posts():
    all_posts_data = []
    page = 1
    per_page_limit = 100
    print(f"📥 Mengambil semua artikel mentah dari WordPress SUMBER: {API_SOURCE_URL}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    while True:
        params = {
            'per_page': per_page_limit,
            'page': page,
            'status': 'publish',
            '_fields': 'id,title,content,date'
        }
        try:
            res = requests.get(API_SOURCE_URL, params=params, headers=headers, timeout=30)
            
            if res.status_code == 400:
                if "rest_post_invalid_page_number" in res.text:
                    print(f"Reached end of posts from WordPress API (page {page} does not exist). Stopping fetch.")
                    break
                else:
                    raise Exception(f"Error: Gagal mengambil data dari WordPress REST API: {res.status_code} - {res.text}. "
                                   f"Pastikan URL API Anda benar dan dapat diakses.")
            elif res.status_code != 200:
                raise Exception(f"Error: Gagal mengambil data dari WordPress REST API: {res.status_code} - {res.text}. "
                               f"Pastikan URL API Anda benar dan dapat diakses.")
            posts_batch = res.json()
            if not posts_batch:
                print(f"Fetched empty batch on page {page}. Stopping fetch.")
                break
            for post in posts_batch:
                all_posts_data.append({
                    'id': post.get('id'),
                    'title': post.get('title', {}).get('rendered', ''),
                    'content': post.get('content', {}).get('rendered', ''),
                    'date': post.get('date', '')
                })
            page += 1
            time.sleep(0.5)
        except requests.exceptions.Timeout:
            print(f"Timeout: Permintaan ke WordPress API di halaman {page} habis waktu. Mungkin ada masalah jaringan atau server lambat.")
            break
        except requests.exceptions.RequestException as e:
            print(f"Network Error: Gagal terhubung ke WordPress API di halaman {page}: {e}. Cek koneksi atau URL.")
            break
    return all_posts_data

# === Fungsi untuk menyisipkan tag <details> ===
def insert_details_tag(content_text, paragraph_limit=10, article_url=None, article_title=None):
    paragraphs = content_text.split('\n\n')
    
    if len(paragraphs) <= paragraph_limit:
        return content_text

    first_part = "\n\n".join(paragraphs[:paragraph_limit])
    rest_part = "\n\n".join(paragraphs[paragraph_limit:])

    encoded_article_url = ""
    encoded_article_title_for_display = ""
    if article_url and article_title:
        encoded_article_url = quote_plus(article_url)
        encoded_article_title_for_display = article_title.replace('"', '&quot;')

    details_tag_start = f'<details><summary><a href="https://lanjutbabdua.github.io/lanjut.html?url={encoded_article_url}#2" rel="nofollow" target="_blank">Lanjut BAB 2: {encoded_article_title_for_display}</a></summary>\n'
    details_tag_end = '\n</details>'
    return first_part + '\n\n' + details_tag_start + rest_part + details_tag_end

# === Eksekusi Utama ===
if __name__ == '__main__':
    print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting WordPress to WordPress publishing process...")
    print(f"🚀 Mengambil artikel dari WordPress SUMBER: {API_SOURCE_URL}.")
    print(f"🎯 Akan memposting ke WordPress TARGET: {WP_TARGET_API_URL}.")
    print("🤖 Fitur Pengeditan Judul dan Konten (300 kata pertama) oleh Gemini AI DINONAKTIFKAN SEMENTARA.")
    print("🖼️ Mencoba menambahkan gambar acak di awal konten.")
    print("📝 Akan menyisipkan tag <details> setelah 10 paragraf pertama dengan link 'Lanjut BAB 2'.")

    try:
        published_ids = load_published_posts_state()
        print(f"Ditemukan {len(published_ids)} postingan yang sudah diterbitkan sebelumnya.")

        random_image_urls = load_image_urls(RANDOM_IMAGES_FILE)
        selected_random_image = get_random_image_url(random_image_urls)
        if not selected_random_image:
            print("⚠️ Tidak ada URL gambar acak yang tersedia. Artikel akan diterbitkan tanpa gambar acak di awal.")

        all_posts_raw_data = fetch_raw_posts()
        print(f"Total {len(all_posts_raw_data)} artikel ditemukan dari WordPress SUMBER.")

        unpublished_posts = [post for post in all_posts_raw_data if str(post['id']) not in published_ids]
        print(f"Ditemukan {len(unpublished_posts)} artikel dari SUMBER yang belum diterbitkan ke TARGET.")

        if not unpublished_posts:
            print("\n🎉 Tidak ada artikel baru yang tersedia untuk diterbitkan hari ini. Proses selesai.")
            exit()

        unpublished_posts.sort(key=lambda x: datetime.datetime.fromisoformat(x['date'].replace('Z', '+00:00')), reverse=True)

        post_to_publish_data = unpublished_posts[0]

        original_id = post_to_publish_data['id']
        original_title = post_to_publish_data['title']
        original_content = post_to_publish_data['content']

        post_date_str = post_to_publish_data['date']
        post_datetime_obj = datetime.datetime.fromisoformat(post_date_str.replace('Z', '+00:00'))
        date_path = post_datetime_obj.strftime('%Y/%m/%d')
        print(f"🗓️ Tanggal untuk URL artikel: {date_path}")

        print(f"🌟 Memproses dan menerbitkan artikel berikutnya: '{original_title}' (ID: {original_id}) dari SUMBER")

        title_after_replacements = replace_custom_words(original_title)
        
        content_no_anchors = remove_anchor_tags(original_content)
        cleaned_formatted_content_before_gemini = strip_html_and_divs(content_no_anchors)
        content_after_replacements = replace_custom_words(cleaned_formatted_content_before_gemini)

        # Gemini AI dinonaktifkan di sini
        final_edited_title = edit_title_with_gemini(
            title_after_replacements
        )

        final_processed_content_text = edit_first_300_words_with_gemini(
            original_id,
            final_edited_title,
            content_after_replacements
        )
        
        # PREDIKSI URL ARTIKEL YANG AKAN TERBIT
        post_slug = slugify(final_edited_title)
        
        base_target_url_for_permalink = "https://ekstracrot.wordpress.com"

        predicted_article_url = f"{base_target_url_for_permalink}/{date_path}/{post_slug}/"
        print(f"🔗 Memprediksi URL artikel target: {predicted_article_url}")

        # === Sisipkan tag <details> setelah konten diedit ===
        content_with_details_tag = insert_details_tag(
            final_processed_content_text,
            paragraph_limit=10,
            article_url=predicted_article_url,
            article_title=final_edited_title
        )
        
        # Konversi ke HTML untuk pengiriman ke WordPress
        final_post_content_html = content_with_details_tag.replace('\n\n', '<p></p>')

        published_result = publish_post_to_wordpress(
            WP_TARGET_API_URL,
            final_edited_title,
            final_post_content_html,
            WP_USERNAME,
            WP_APP_PASSWORD,
            random_image_url=selected_random_image
        )
        
        if published_result:
            published_ids.add(str(original_id))
            save_published_posts_state(published_ids)
            print(f"✅ State file '{STATE_FILE}' diperbarui dengan ID post dari SUMBER: {original_id}.")
            print("\n🎉 Proses Selesai! Artikel telah diterbitkan ke WordPress TARGET.")
        else:
            print("\n❌ Gagal menerbitkan artikel ke WordPress TARGET. State file tidak diperbarui.")

    except Exception as e:
        print(f"❌ Terjadi kesalahan fatal: {e}")
        import traceback
        traceback.print_exc()
