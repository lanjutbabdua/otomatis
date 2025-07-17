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

# Ganti langsung dengan blog identifier WordPress.com kamu
# Contoh: "marwanmedias.wordpress.com" atau "yourcustomdomain.com"
WORDPRESS_COM_BLOG_IDENTIFIER = "marwanmedias.wordpress.com" 

# Endpoint untuk publikasi ke WordPress.com. Akan dibentuk dengan WORDPRESS_COM_BLOG_IDENTIFIER
WORDPRESS_COM_PUBLISH_BASE_URL = "https://public-api.wordpress.com/rest/v1.1/sites/"

STATE_FILE = 'published_posts.json' # File untuk melacak postingan yang sudah diterbitkan
RANDOM_IMAGES_FILE = 'random_images.json' # File untuk URL gambar acak

# --- Konfigurasi WordPress.com (Untuk PUBLISH, Menggunakan Access Token Langsung) ---
# MASUKKAN ACCESS TOKEN KAMU LANGSUNG DI SINI
WORDPRESS_COM_ACCESS_TOKEN = "soFFpv*$xVc#sXF5IwwOM(gxu#wxcC8OnGX4#v5OR(z7t#!J#vC#KSmNs3@y(fYM"

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

def insert_more_tag(content_html, word_limit=100):
    """
    Menyisipkan tag di sekitar batas kata yang ditentukan dalam konten HTML.
    Akan mencari lokasi yang "aman" seperti setelah tag penutup paragraf atau baris baru.
    """
    words = content_html.split()
    if len(words) <= word_limit:
        return content_html # Tidak perlu menyisipkan jika konten terlalu pendek

    preview_content = " ".join(words[:word_limit])
    
    insert_pos = -1
    
    # Prioritaskan untuk menyisipkan setelah penutup tag paragraf jika ada di sekitar batas
    match = re.search(r'<\/p>', preview_content)
    if match:
        insert_pos = content_html.find(match.group(0), 0, len(preview_content)) + len(match.group(0))
    else:
        # Jika tidak ada paragraf penutup, cari spasi terdekat setelah batas kata
        space_after_limit = content_html.find(' ', len(preview_content))
        if space_after_limit != -1:
            insert_pos = space_after_limit
        else:
            insert_pos = len(preview_content) # Fallback: potong di akhir kata ke-100

    if insert_pos != -1:
        return content_html[:insert_pos].strip() + "\n\n" + content_html[insert_pos:].strip()
    
    return content_html # Fallback jika gagal menyisipkan dengan rapi

def wrap_content_in_details_tag(content_html, article_url, article_title, word_limit=700):
    """
    Menyisipkan tag <details> dan <summary> untuk menyembunyikan sisa konten
    setelah batas kata yang ditentukan, dengan tautan URL dan judul artikel di summary.
    """
    words = content_html.split()
    if len(words) <= word_limit:
        return content_html # Tidak perlu menyembunyikan jika konten terlalu pendek

    # Cari posisi karakter untuk word_limit
    temp_preview_words = " ".join(words[:word_limit])
    insert_point_char = len(temp_preview_words)
    
    # Pastikan kita tidak memotong tag HTML atau kata
    safe_insert_pos = -1
    
    # Coba cari tag penutup paragraf atau div di sekitar batas kata
    # Batasi pencarian agar tidak terlalu jauh
    search_end_pos = min(len(content_html), insert_point_char + 200) # Cari dalam 200 karakter berikutnya
    match = re.search(r'(<\/\w+>)\s*(<\w+[^>]*>)?', content_html[insert_point_char:search_end_pos], re.IGNORECASE)
    
    if match:
        safe_insert_pos = content_html.find(match.group(0), insert_point_char) + len(match.group(0))
    else:
        # Jika tidak ada tag penutup, cari spasi terdekat setelah batas kata
        space_pos = content_html.find(' ', insert_point_char)
        if space_pos != -1:
            safe_insert_pos = space_pos
        else:
            safe_insert_pos = insert_point_char # Fallback: potong di akhir karakter ke-700
    
    if safe_insert_pos != -1:
        part_before_details = content_html[:safe_insert_pos].strip()
        part_inside_details = content_html[safe_insert_pos:].strip()
        
        # Bentuk teks summary sesuai permintaan
        # Escape HTML entities di judul untuk mencegah masalah rendering
        escaped_title = article_title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#039;')
        
        # Menggunakan shrinkearn.com link
        details_summary_html = f"<summary><a href='https://shrinkearn.com/st?api=bd1828880f4bb9d0e34fed8fc3214e4cc14959ad&url={article_url}' rel='nofollow' target='_blank'>Lanjut bab 2: {escaped_title}</a></summary>"
        
        # Gabungkan semua bagian
        return (
            f"{part_before_details}\n"
            f"<details>{details_summary_html}\n"
            f"<div id=\"lanjut\">\n{part_inside_details}\n</div>\n"
            f"</details>\n"
        )
    
    return content_html # Fallback jika gagal menyisipkan dengan rapi


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

# --- Penerbitan Artikel ke WordPress.com ---

def publish_post_to_wordpress_com(access_token, blog_identifier, title, content_html, categories=None, tags=None, random_image_url=None, article_url_for_details=None, article_title_for_details=None):
    """
    Menerbitkan postingan ke WordPress.com.
    """
    print(f"🚀 Menerbitkan '{title}' ke WordPress.com...")

    publish_url = f"{WORDPRESS_COM_PUBLISH_BASE_URL}{blog_identifier}/posts/new"

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

    # 1. SISIPKAN DI SINI (jika diperlukan)
    content_after_more_tag = insert_more_tag(content_html, word_limit=100)
    
    # 2. SISIPKAN <details> DI SINI (jika diperlukan), sekarang dengan URL dan judul
    final_content_for_publish = wrap_content_in_details_tag(
        content_after_more_tag, 
        article_url=article_url_for_details, 
        article_title=article_title_for_details, 
        word_limit=700
    )
    
    payload = {
        'title': title,
        'content': final_content_for_publish, 
        'status': 'publish' # Bisa diubah ke 'draft' jika ingin meninjau dulu
    }

    if categories:
        payload['categories'] = {cat: True for cat in categories}
    if tags:
        payload['tags'] = {tag: True for tag in tags}

    try:
        response = requests.post(publish_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        response_data = response.json()
        print(f"✅ Artikel '{title}' berhasil diterbitkan ke WordPress.com! URL: {response_data.get('URL')}")
        return response_data
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal menerbitkan artikel '{title}' ke WordPress.com: {e}")
        if response.status_code == 409:
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
            '_fields': 'id,title,content,excerpt,categories,tags,date,featured_media,link' # Tambahkan 'link' untuk URL sumber
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
            time.sleep(0.5) # Jeda sebentar untuk menghindari overloading server

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
        post['source_link'] = post.get('link') # Tambahkan link sumber ke data post

        # Ekstrak kategori dan tag
        post['category_names'] = [] # Isi ini jika kamu mapping ID ke nama
        post['tag_names'] = []      # Isi ini jika kamu mapping ID ke nama

        processed_posts.append(post)

    return processed_posts

# --- Eksekusi Utama ---

if __name__ == '__main__':
    print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting WordPress self-hosted to WordPress.com publishing process (Batch Mode)...")
    print("🚀 Mengambil semua artikel WordPress self-hosted.")
    print("🤖 Fitur Pengeditan 300 Kata Pertama oleh Gemini AI DINONAKTIFKAN.")
    print("🖼️ Mencoba mengambil gambar pertama dari konten artikel.")
    print("Directly publishing ALL available articles to WordPress.com.")
    print("📝 Menyisipkan di sekitar 100 kata pertama setiap artikel.")
    print("🔽 Menyisipkan <details> dengan link judul artikel sumber setelah 700 kata pertama setiap artikel.")

    # Variabel tidak lagi diambil dari os.getenv()
    wpcom_access_token = WORDPRESS_COM_ACCESS_TOKEN
    wordpress_com_blog_identifier = WORDPRESS_COM_BLOG_IDENTIFIER

    # Tidak perlu validasi os.getenv() lagi karena sudah disetel langsung
    # required_env_vars = ["WORDPRESS_COM_ACCESS_TOKEN", "WORDPRESS_COM_BLOG_IDENTIFIER"]
    # for var in required_env_vars:
    #     if not os.getenv(var):
    #         print(f"❌ Error: Variabel lingkungan '{var}' tidak disetel.")
    #         print("Pastikan Anda sudah mendapatkan access token dan blog identifier dari WordPress.com dan menyetelnya sebagai variabel lingkungan.")
    #         exit()

    try:
        # 1. Muat daftar postingan yang sudah diterbitkan
        published_ids = load_published_posts_state()
        print(f"Ditemukan {len(published_ids)} postingan yang sudah diterbitkan sebelumnya.")

        # 2. Muat URL gambar acak
        random_image_urls = load_image_urls(RANDOM_IMAGES_FILE)
        
        # 3. Ambil semua postingan dari API WordPress self-hosted dan lakukan pre-processing
        all_posts_preprocessed = fetch_all_and_process_posts_from_self_hosted()
        print(f"Total {len(all_posts_preprocessed)} artikel ditemukan dan diproses awal dari WordPress self-hosted API.")

        # 4. Filter postingan yang belum diterbitkan
        # Pastikan kita membandingkan string untuk ID
        unpublished_posts = [post for post in all_posts_preprocessed if str(post['id']) not in published_ids]
        print(f"Ditemukan {len(unpublished_posts)} artikel yang belum diterbitkan yang akan diproses.")

        if not unpublished_posts:
            print("\n🎉 Tidak ada artikel baru yang tersedia untuk diterbitkan. Proses selesai.")
            exit()

        # 5. Urutkan postingan yang belum diterbitkan (misalnya, dari yang TERBARU)
        unpublished_posts.sort(key=lambda x: datetime.datetime.fromisoformat(x['date'].replace('Z', '+00:00')), reverse=True)

        successful_publications = 0
        failed_publications = 0

        # 6. Iterasi dan terbitkan setiap postingan yang belum diterbitkan
        for post_to_publish in unpublished_posts:
            original_post_id = post_to_publish.get('id')
            processed_title = post_to_publish.get('processed_title')
            source_article_url = post_to_publish.get('source_link', '#') # Ambil link sumber, fallback ke '#'
            final_processed_content = post_to_publish['raw_cleaned_content']
            
            # Konversi konten akhir ke HTML untuk WordPress.com
            final_content_html = markdown.markdown(final_processed_content)

            # Ambil gambar acak UNTUK SETIAP postingan (jika mode batch)
            selected_random_image = get_random_image_url(random_image_urls)
            if not selected_random_image:
                print(f"⚠️ Tidak ada URL gambar acak yang tersedia untuk artikel '{processed_title}'.")

            print(f"\n🌟 Memproses artikel: '{processed_title}' (ID Sumber: {original_post_id})")

            # 7. Terbitkan ke WordPress.com
            published_response = publish_post_to_wordpress_com(
                wpcom_access_token,
                wordpress_com_blog_identifier,
                processed_title,
                final_content_html, 
                categories=post_to_publish['category_names'],
                tags=post_to_publish['tag_names'],
                random_image_url=selected_random_image,
                # Teruskan URL sumber dan judul ke fungsi publish_post_to_wordpress_com
                # untuk digunakan di wrap_content_in_details_tag
                article_url_for_details=source_article_url, 
                article_title_for_details=processed_title
            )

            if published_response:
                successful_publications += 1
                # 8. Tambahkan ID postingan ke daftar yang sudah diterbitkan dan simpan state
                published_ids.add(str(original_post_id))
                save_published_posts_state(published_ids)
                print(f"✅ State file '{STATE_FILE}' diperbarui dengan ID: {original_post_id}.")
            else:
                failed_publications += 1
                print(f"❌ Gagal menerbitkan artikel ID Sumber: {original_post_id}. Tidak ditambahkan ke state file.")
            
            time.sleep(random.uniform(2, 5)) # Jeda acak antar postingan untuk menghindari rate limiting

        print(f"\n--- Proses Batch Selesai ---")
        print(f"Total artikel diproses dari sumber: {len(all_posts_preprocessed)}")
        print(f"Artikel baru yang ditemukan: {len(unpublished_posts)}")
        print(f"✅ Berhasil diterbitkan ke WordPress.com: {successful_publications}")
        print(f"❌ Gagal diterbitkan ke WordPress.com: {failed_publications}")
        print("\n🎉 Proses Batch Selesai!")

    except Exception as e:
        print(f"❌ Terjadi kesalahan fatal selama proses: {e}")
        import traceback
        traceback.print_exc()
