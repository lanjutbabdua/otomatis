import requests
import os
import re
import json
import datetime
import time
import random
import markdown # Markdown tetap diperlukan untuk konversi ke HTML


# --- Konfigurasi ---
# INI ADALAH URL API WORDPRESS SELF-HOSTED KAMU (SUMBER ARTIKEL)
API_BASE_URL_SELF_HOSTED = "https://kingquizzes.com/wp-json/wp/v2/posts"

# INI ADALAH URL API WORDPRESS.COM KAMU (TUJUAN ARTIKEL)
# Ganti YOUR_WORDPRESS_COM_SITE_SLUG dengan slug situs WordPress.com kamu (contoh: 'myawesomeblog')
# ATAU jika kamu punya custom domain di WordPress.com: "https://public-api.wordpress.com/rest/v1.1/sites/yourcustomdomain.com/posts/new"
WORDPRESS_COM_PUBLISH_URL = "https://public-api.wordpress.com/rest/v1.1/sites/bursaceritahot.wordpress.com/posts/new"

STATE_FILE = 'published_posts.json' # File untuk melacak postingan yang sudah diterbitkan
RANDOM_IMAGES_FILE = 'random_images.json' # File untuk URL gambar acak

# --- Konfigurasi WordPress.com (Untuk PUBLISH, Menggunakan OAuth 2.0) ---
WORDPRESS_COM_CLIENT_ID = os.getenv("WORDPRESS_COM_CLIENT_ID")
WORDPRESS_COM_CLIENT_SECRET = os.getenv("WORDPRESS_COM_CLIENT_SECRET")
WORDPRESS_COM_REFRESH_TOKEN = os.getenv("WORDPRESS_COM_REFRESH_TOKEN") # Refresh token WordPress.com

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
    """
    Mencari URL gambar pertama di dalam konten HTML.
    """
    match = re.search(r'<img[^>]+src="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def strip_html_and_divs(html):
    """
    Menghapus sebagian besar tag HTML, kecuali yang esensial,
    dan mengganti </p> dengan dua newline untuk pemisahan paragraf.
    """
    html_with_newlines = re.sub(r'</p>', r'\n\n', html, flags=re.IGNORECASE)
    html_no_images = re.sub(r'<img[^>]*>', '', html_with_newlines)
    html_no_divs = re.sub(r'</?div[^>]*>', '', html_no_images, flags=re.IGNORECASE)
    clean_text = re.sub('<[^<]+?>', '', html_no_divs)
    clean_text = re.sub(r'\n{3,}', r'\n\n', clean_text).strip()
    return clean_text

def remove_anchor_tags(html_content):
    """Menghapus tag <a> tapi mempertahankan teks di dalamnya."""
    return re.sub(r'<a[^>]*>(.*?)<\/a>', r'\1', html_content)

def sanitize_filename(title):
    """Membersihkan judul agar cocok untuk nama file."""
    clean_title = re.sub(r'[^\w\s-]', '', title).strip().lower()
    return re.sub(r'[-\s]+', '-', clean_title)

def replace_custom_words(text):
    """Menerapkan penggantian kata khusus pada teks."""
    processed_text = text
    sorted_replacements = sorted(REPLACEMENT_MAP.items(), key=lambda item: len(item[0]), reverse=True)
    for old_word, new_word in sorted_replacements:
        pattern = re.compile(re.escape(old_word), re.IGNORECASE)
        processed_text = pattern.sub(new_word, processed_text)
    return processed_text

# --- Fungsi untuk memuat dan menyimpan status postingan yang sudah diterbitkan ---
def load_published_posts_state():
    """Memuat ID postingan yang sudah diterbitkan dari file state."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print(f"Warning: {STATE_FILE} is corrupted or empty. Starting with an empty published posts list.")
                return set()
    return set()

def save_published_posts_state(published_ids):
    """Menyimpan ID postingan yang sudah diterbitkan ke file state."""
    with open(STATE_FILE, 'w') as f:
        json.dump(list(published_ids), f)

def load_image_urls(file_path):
    """
    Memuat daftar URL gambar dari file JSON.
    """
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
    """
    Memilih URL gambar secara acak dari daftar.
    """
    if image_urls:
        return random.choice(image_urls)
    return None

# --- Otentikasi WordPress.com ---

def get_wordpress_com_access_token():
    """
    Menggunakan refresh token WordPress.com untuk mendapatkan token akses baru.
    """
    if not all([WORDPRESS_COM_CLIENT_ID, WORDPRESS_COM_CLIENT_SECRET, WORDPRESS_COM_REFRESH_TOKEN]):
        raise ValueError(
            "WORDPRESS_COM_CLIENT_ID, WORDPRESS_COM_CLIENT_SECRET, dan WORDPRESS_COM_REFRESH_TOKEN "
            "variabel lingkungan harus disetel untuk otentikasi WordPress.com OAuth."
        )

    token_url = "https://public-api.wordpress.com/oauth2/token"
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': WORDPRESS_COM_REFRESH_TOKEN,
        'client_id': WORDPRESS_COM_CLIENT_ID,
        'client_secret': WORDPRESS_COM_CLIENT_SECRET
    }

    try:
        response = requests.post(token_url, data=payload)
        response.raise_for_status() # Akan menimbulkan HTTPError untuk status kode 4xx/5xx
        return response.json()['access_token']
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal mendapatkan token akses WordPress.com: {e}")
        print("Pastikan WORDPRESS_COM_CLIENT_ID, WORDPRESS_COM_CLIENT_SECRET, dan WORDPRESS_COM_REFRESH_TOKEN Anda valid.")
        raise

# --- Penerbitan Artikel ke WordPress.com ---

def publish_post_to_wordpress_com(access_token, title, content_html, categories=None, tags=None, random_image_url=None):
    """
    Menerbitkan postingan ke WordPress.com.
    """
    print(f"🚀 Menerbitkan '{title}' ke WordPress.com...")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'User-Agent': 'WordPress-to-WPcom-Migrator/1.0'
    }

    # Tambahkan gambar acak di awal konten jika ada
    if random_image_url:
        image_html = f'<p style="text-align: center;"><img src="{random_image_url}" alt="{title}" style="max-width: 100%; height: auto; display: block; margin: 0 auto; border-radius: 8px;"></p>'
        content_html = image_html + "\n" + content_html
        print(f"🖼️ Gambar acak '{random_image_url}' ditambahkan ke artikel.")

    payload = {
        'title': title,
        'content': content_html,
        'status': 'publish' # Bisa diubah ke 'draft' jika ingin meninjau dulu
    }

    if categories:
        payload['categories'] = {cat: True for cat in categories} # WordPress.com API expects this format
    if tags:
        payload['tags'] = {tag: True for tag in tags} # WordPress.com API expects this format

    try:
        response = requests.post(WORDPRESS_COM_PUBLISH_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status() # Tangani error HTTP
        response_data = response.json()
        print(f"✅ Artikel '{title}' berhasil diterbitkan ke WordPress.com! URL: {response_data.get('URL')}")
        return response_data
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal menerbitkan artikel '{title}' ke WordPress.com: {e}")
        if response.status_code == 409: # Conflict, mungkin post dengan judul/konten serupa sudah ada
            print("Peringatan: Mungkin artikel ini sudah ada di WordPress.com. Coba cek secara manual.")
        return None

# --- Pengambilan Artikel dari WordPress Self-Hosted (Sumber) ---

def fetch_all_and_process_posts_from_self_hosted():
    """
    Mengambil semua postingan dari WordPress self-hosted REST API, membersihkan HTML,
    dan menerapkan penggantian kata khusus.
    """
    all_posts_raw = []
    page = 1
    per_page_limit = 100

    print("📥 Mengambil semua artikel dari WordPress self-hosted REST API...")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    while True:
        params = {
            'per_page': per_page_limit,
            'page': page,
            'status': 'publish',
            '_fields': 'id,title,content,excerpt,categories,tags,date,featured_media'
        }
        try:
            res = requests.get(API_BASE_URL_SELF_HOSTED, params=params, headers=headers, timeout=30)

            if res.status_code == 400:
                if "rest_post_invalid_page_number" in res.text:
                    print(f"Reached end of posts from WordPress self-hosted API (page {page} does not exist). Stopping fetch.")
                    break
                else:
                    raise Exception(f"Error: Gagal mengambil data dari WordPress self-hosted REST API: {res.status_code} - {res.text}. "
                                     f"Pastikan URL API Anda benar dan dapat diakses.")
            elif res.status_code != 200:
                raise Exception(f"Error: Gagal mengambil data dari WordPress self-hosted REST API: {res.status_code} - {res.text}. "
                                f"Pastikan URL API Anda benar dan dapat diakses.")

            posts_batch = res.json()

            if not posts_batch:
                print(f"Fetched empty batch on page {page}. Stopping fetch.")
                break

            all_posts_raw.extend(posts_batch)
            page += 1
            time.sleep(0.5)

        except requests.exceptions.Timeout:
            print(f"Timeout: Permintaan ke WordPress self-hosted API di halaman {page} habis waktu. Mungkin ada masalah jaringan atau server lambat.")
            break
        except requests.exceptions.RequestException as e:
            print(f"Network Error: Gagal terhubung ke WordPress self-hosted API di halaman {page}: {e}. Cek koneksi atau URL.")
            break

    processed_posts = []
    for post in all_posts_raw:
        original_title = post.get('title', {}).get('rendered', '')
        processed_title = replace_custom_words(original_title)
        post['processed_title'] = processed_title

        raw_content = post.get('content', {}).get('rendered', '')
        content_image_url = extract_first_image_url(raw_content)
        post['content_image_url'] = content_image_url

        content_no_anchors = remove_anchor_tags(raw_content)
        cleaned_formatted_content = strip_html_and_divs(content_no_anchors)
        content_after_replacements = replace_custom_words(cleaned_formatted_content)

        post['raw_cleaned_content'] = content_after_replacements
        post['id'] = post.get('id')

        # Ekstrak kategori dan tag
        # Perlu dicatat: WordPress.com API membutuhkan NAMA kategori/tag, bukan ID.
        # Untuk mendapatkan nama, kamu perlu membuat permintaan tambahan ke API self-hosted
        # untuk /wp/v2/categories dan /wp/v2/tags.
        # Untuk percobaan awal, saya akan meninggalkan ini kosong atau gunakan ID sebagai placeholder.
        # Jika kamu ingin kategori/tag yang akurat, kamu harus mengimplementasikan pemetaan ID ke nama.
        post['category_names'] = []
        post['tag_names'] = []

        processed_posts.append(post)

    return processed_posts

# --- Eksekusi Utama ---

if __name__ == '__main__':
    print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting WordPress self-hosted to WordPress.com publishing process...")
    print("🚀 Mengambil semua artikel WordPress self-hosted.")
    print("🤖 Fitur Pengeditan 300 Kata Pertama oleh Gemini AI DINONAKTIFKAN.") # Notifikasi perubahan
    print("🖼️ Mencoba mengambil gambar pertama dari konten artikel.")
    print("Directly publishing to WordPress.com.")

    # Validasi lingkungan untuk WordPress.com (Tujuan)
    if not all([WORDPRESS_COM_CLIENT_ID, WORDPRESS_COM_CLIENT_SECRET, WORDPRESS_COM_REFRESH_TOKEN]):
        print("❌ Error: Variabel lingkungan WORDPRESS_COM_CLIENT_ID, WORDPRESS_COM_CLIENT_SECRET, atau WORDPRESS_COM_REFRESH_TOKEN tidak disetel.")
        print("Pastikan Anda sudah mendapatkan kredensial OAuth 2.0 dari WordPress.com.")
        exit()

    try:
        # 1. Muat daftar postingan yang sudah diterbitkan
        published_ids = load_published_posts_state()
        print(f"Ditemukan {len(published_ids)} postingan yang sudah diterbitkan sebelumnya.")

        # 2. Muat URL gambar acak
        random_image_urls = load_image_urls(RANDOM_IMAGES_FILE)
        selected_random_image = get_random_image_url(random_image_urls)
        if not selected_random_image:
            print("⚠️ Tidak ada URL gambar acak yang tersedia. Artikel akan diterbitkan tanpa gambar acak.")

        # 3. Ambil semua postingan dari API WordPress self-hosted dan lakukan pre-processing
        all_posts_preprocessed = fetch_all_and_process_posts_from_self_hosted()
        print(f"Total {len(all_posts_preprocessed)} artikel ditemukan dan diproses awal dari WordPress self-hosted API.")

        # 4. Filter postingan yang belum diterbitkan
        unpublished_posts = [post for post in all_posts_preprocessed if str(post['id']) not in published_ids]
        print(f"Ditemukan {len(unpublished_posts)} artikel yang belum diterbitkan.")

        if not unpublished_posts:
            print("\n🎉 Tidak ada artikel baru yang tersedia untuk diterbitkan hari ini. Proses selesai.")
            exit()

        # 5. Urutkan postingan yang belum diterbitkan dari yang TERBARU
        unpublished_posts.sort(key=lambda x: datetime.datetime.fromisoformat(x['date'].replace('Z', '+00:00')), reverse=True)

        # 6. Pilih satu postingan untuk diterbitkan hari ini
        post_to_publish = unpublished_posts[0]

        print(f"🌟 Memproses dan menerbitkan artikel berikutnya: '{post_to_publish.get('processed_title')}' (ID: {post_to_publish.get('id')})")

        # Konten akhir langsung dari hasil pembersihan dan penggantian kata
        final_processed_content = post_to_publish['raw_cleaned_content']
        # Convert final content to HTML for WordPress.com
        final_content_html = markdown.markdown(final_processed_content)


        # 7. Dapatkan token akses WordPress.com
        wpcom_access_token = get_wordpress_com_access_token()

        # 8. Terbitkan ke WordPress.com
        if wpcom_access_token:
            publish_post_to_wordpress_com(
                wpcom_access_token,
                post_to_publish['processed_title'],
                final_content_html,
                categories=post_to_publish['category_names'],
                tags=post_to_publish['tag_names'],
                random_image_url=selected_random_image
            )
        else:
            print("Skipping WordPress.com publishing: Gagal mendapatkan token akses WordPress.com.")

        # 9. Tambahkan ID postingan ke daftar yang sudah diterbitkan dan simpan state
        published_ids.add(str(post_to_publish['id']))
        save_published_posts_state(published_ids)
        print(f"✅ State file '{STATE_FILE}' diperbarui.")

        print("\n🎉 Proses Selesai! Artikel telah diterbitkan langsung ke WordPress.com.")

    except Exception as e:
        print(f"❌ Terjadi kesalahan fatal: {e}")
        import traceback
        traceback.print_exc()
