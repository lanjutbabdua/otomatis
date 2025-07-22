import os
import requests
import json
import datetime
import time
import random
import re
import markdown
import google.generativeai as genai
import unicodedata
from urllib.parse import quote_plus

# Impor library XML-RPC
from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods.posts import NewPost
from wordpress_xmlrpc.methods.media import UploadFile # Diimpor, tapi tidak digunakan untuk upload langsung di sini

# --- Konfigurasi ---
API_SOURCE_URL = "https://kisah69.blog/wp-json/wp/v2/posts"
# Ganti WP_TARGET_API_URL untuk XML-RPC
WP_TARGET_API_URL = "https://ekstracrot.wordpress.com/xmlrpc.php"
# ID Blog untuk WordPress.com (perlu untuk XML-RPC pada public-api)
# Untuk ekstracrot.wordpress.com, ID situsnya adalah 137050535
WP_BLOG_ID = "137050535" 

STATE_FILE = 'artikel_terbit.json'
RANDOM_IMAGES_FILE = 'random_images.json'

# --- Konfigurasi Gemini API (Satu Key Saja) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_CONTENT")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY_CONTENT environment variable not set. Please set it in your GitHub Secrets or local environment.")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model_content = genai.GenerativeModel("gemini-1.5-flash")
gemini_model_title = genai.GenerativeModel("gemini-1.5-flash")

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
    """
    Mengekstrak URL gambar pertama dari konten HTML.
    """
    match = re.search(r'<img[^>]+src="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def strip_html_and_divs(html):
    """
    Menghapus tag HTML (termasuk <div>) dan gambar, 
    mengganti </p> dengan newline ganda, dan membersihkan spasi berlebih.
    """
    html_with_newlines = re.sub(r'</p>', r'\n\n', html, flags=re.IGNORECASE)
    html_no_images = re.sub(r'<img[^>]*>', '', html_with_newlines)
    html_no_divs = re.sub(r'</?div[^>]*>', '', html_no_images, flags=re.IGNORECASE)
    clean_text = re.sub('<[^<]+?>', '', html_no_divs) # This regex does not remove <!--more-->
    clean_text = re.sub(r'\n{3,}', r'\n\n', clean_text).strip()
    return clean_text

def remove_anchor_tags(html_content):
    """
    Menghapus tag <a> tetapi mempertahankan teks di dalamnya.
    """
    return re.sub(r'<a[^>]*>(.*?)<\/a>', r'\1', html_content)

def sanitize_filename(title):
    """
    Membersihkan judul untuk digunakan sebagai nama file yang aman.
    """
    clean_title = re.sub(r'[^\w\s-]', '', title).strip().lower()
    return re.sub(r'[-\s]+', '-', clean_title)

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    Digunakan untuk membuat slug URL yang bersih.
    """
    value = str(value)
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('utf-8')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'[-\s]+', '-', value)

def replace_custom_words(text):
    """
    Mengganti kata-kata tertentu dalam teks berdasarkan REPLACEMENT_MAP.
    Penggantian dilakukan dari kata terpanjang terlebih dahulu untuk menghindari parsial.
    """
    processed_text = text
    sorted_replacements = sorted(REPLACEMENT_MAP.items(), key=lambda item: len(item[0]), reverse=True)
    for old_word, new_word in sorted_replacements:
        pattern = re.compile(re.escape(old_word), re.IGNORECASE)
        processed_text = pattern.sub(new_word, processed_text)
    return processed_text

def edit_title_with_gemini(original_title):
    """
    Mengedit judul menggunakan Gemini AI untuk membuatnya lebih menarik dan tidak vulgar.
    """
    print(f"🤖 Memulai pengeditan judul dengan Gemini AI (Model Judul): '{original_title}'...")
    try:
        prompt = (
            f"Saya membutuhkan satu judul baru yang lebih menarik, tidak vulgar, dan tetap relevan dengan topik aslinya dan menggunakan kata Cerita Dewasa kedalamnya. "
            f"Judul harus clickbait yang memancing rasa penasaran tanpa mengurangi keamanan konten. "
            f"**HANYA BERIKAN SATU JUDUL BARU, TANPA PENJELASAN ATAU TEKS TAMBAKAH APAPUN.**\n\n"
            f"Judul asli: '{original_title}'\n\n"
            f"Judul baru:"
        )
        response = gemini_model_title.generate_content(prompt)
        edited_title = response.text.strip()
        if edited_title.startswith('"') and edited_title.endswith('"'):
            edited_title = edited_title[1:-1]
            
        print(f"✅ Gemini AI (Model Judul) selesai mengedit judul. Hasil: '{edited_title}'")
        return edited_title
    except Exception as e:
        print(f"❌ Error saat mengedit judul dengan Gemini AI (Model Judul): {e}. Menggunakan judul asli.")
        return original_title

def edit_first_300_words_with_gemini(post_id, post_title, full_text_content):
    """
    Mengedit 300 kata pertama dari konten artikel menggunakan Gemini AI.
    Tujuannya adalah untuk membuat narasi yang lebih halus dan sopan.
    Setelah itu, menyisipkan tag [more] untuk pemotongan di homepage.
    """
    words = full_text_content.split()
    if len(words) < 50:
        print(f"[{post_id}] Artikel terlalu pendek (<50 kata) untuk diedit oleh Gemini AI. Melewati pengeditan.")
        return full_text_content

    char_count_for_300_words = 0
    word_count = 0
    for i, word in enumerate(words):
        if word_count < 300:
            char_count_for_300_words += len(word)
            if i < len(words) - 1:
                char_count_for_300_words += 1
            word_count += 1
        else:
            break
            
    char_count_for_300_words = min(char_count_for_300_words, len(full_text_content))
    first_300_words_original_string = full_text_content[:char_count_for_300_words].strip()
    rest_of_article_text = full_text_content[char_count_for_300_words:].strip()

    print(f"🤖 Memulai pengeditan Gemini AI (Model Konten) untuk artikel ID: {post_id} - '{post_title}' ({len(first_300_words_original_string.split())} kata pertama)...")
    try:
        prompt = (
            f"Saya ingin Anda menulis ulang paragraf pembuka dari sebuah cerita. "
            f"Tujuannya adalah untuk membuat narasi yang mengalir, menarik perhatian pembaca, dan mempertahankan inti cerita asli, "
            f"tetapi dengan gaya bahasa yang lebih halus dan sopan, menghindari bahasa yang eksplisit atau vulgar. "
            f"Paragraf harus tetap panjangnya sekitar 300 kata dari teks asli, tetapi dengan kosakata dan struktur kalimat yang diubah secara signifikan. "
            f"Gunakan gaya informal dan lugas. Pastikan tidak ada konten yang melanggar pedoman keamanan.\n\n"
            f"Berikut adalah paragraf aslinya:\n\n"
            f"{first_300_words_original_string}"
            f"\n\nParagraf yang ditulis ulang:"
        )
        response = gemini_model_content.generate_content(prompt)
        edited_text_from_gemini = response.text
        print(f"✅ Gemini AI (Model Konten) selesai mengedit bagian pertama artikel ID: {post_id}.")
        
        # Membersihkan teks hasil Gemini
        cleaned_edited_text = strip_html_and_divs(edited_text_from_gemini)
        
        # Sisipkan tag [more] di sini untuk pemotongan di homepage
        final_combined_text_with_more = cleaned_edited_text.strip() + "\n<!--more-->\n" + rest_of_article_text.strip()
        
        # Pastikan tidak ada tag HTML yang tidak diinginkan setelah penggabungan
        return strip_html_and_divs(final_combined_text_with_more)

    except Exception as e:
        print(f"❌ Error saat mengedit dengan Gemini AI (Model Konten) untuk artikel ID: {post_id} - {e}. Menggunakan teks asli untuk bagian ini.")
        return full_text_content

# --- Fungsi untuk memuat dan menyimpan status postingan yang sudah diterbitkan ---
def load_published_posts_state():
    """
    Memuat ID postingan yang sudah diterbitkan dari file status.
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print(f"Warning: {STATE_FILE} is corrupted or empty. Starting with an empty published posts list.")
                return set()
    return set()

def save_published_posts_state(published_ids):
    """
    Menyimpan ID postingan yang sudah diterbitkan ke file status.
    """
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
    Mengambil URL gambar acak dari daftar yang dimuat.
    """
    if image_urls:
        return random.choice(image_urls)
    return None

# --- Fungsi yang Dimodifikasi untuk Mengirim Post ke WordPress Target Menggunakan XML-RPC ---
def publish_post_to_wordpress(wp_xmlrpc_url, blog_id, title, content_html, username, app_password, random_image_url=None, post_status='publish'):
    """
    Menerbitkan artikel ke WordPress.com menggunakan XML-RPC API.
    Menambahkan gambar acak di awal konten jika tersedia.
    """
    print(f"🚀 Menerbitkan '{title}' ke WordPress via XML-RPC: {wp_xmlrpc_url}...")
    final_content_for_wp = content_html
    
    if random_image_url:
        image_html = f'<p><img src="{random_image_url}" alt="{title}" style="max-width: 100%; height: auto; display: block; margin: 0 auto;"></p>'
        final_content_for_wp = image_html + "\n\n" + content_html
        print(f"🖼️ Gambar acak '{random_image_url}' ditambahkan ke artikel.")

    # --- Debugging: Cek Kredensial ---
    if not username or not app_password:
        print("❌ ERROR: WP_USERNAME atau WP_APP_PASSWORD tidak diatur dengan benar untuk proses publikasi.")
        return None

    try:
        # Inisialisasi klien XML-RPC
        client = Client(wp_xmlrpc_url, username, app_password)
        
        # Membuat objek post
        post = WordPressPost()
        post.title = title
        post.content = final_content_for_wp
        post.post_status = post_status
        post.slug = slugify(title) # XML-RPC juga mendukung slug

        # Debugging payload
        print("\n--- Debugging Detail Payload XML-RPC ---")
        print(f"URL XML-RPC: {wp_xmlrpc_url}")
        print(f"Blog ID: {blog_id}")
        print(f"Username: {username}")
        print(f"Title: {post.title}")
        print(f"Status: {post.post_status}")
        print(f"Slug: {post.slug}")
        content_preview = post.content[:500] + '...' if len(post.content) > 500 else post.content
        print(f"Content Preview (sebagian): {content_preview}")
        print("---------------------------------------\n")

        # Mengirim post baru
        # Catatan: Untuk WordPress.com, metode NewPost memerlukan blog_id sebagai argumen pertama
        post_id = client.call(NewPost(post, blog_id=blog_id))
        
        # XML-RPC NewPost biasanya hanya mengembalikan ID, bukan URL.
        # URL akan diprediksi di main loop.
        print(f"✅ Artikel '{title}' berhasil diterbitkan ke WordPress via XML-RPC! Post ID: {post_id}")
        return {'id': post_id, 'URL': None} # URL akan diprediksi di main loop

    except Exception as e:
        print(f"❌ Terjadi kesalahan saat memposting ke WordPress via XML-RPC: {e}")
        # Tangani error spesifik dari XML-RPC jika memungkinkan
        if hasattr(e, 'faultCode') and hasattr(e, 'faultString'):
            print(f"XML-RPC Fault Code: {e.faultCode}")
            print(f"XML-RPC Fault String: {e.faultString}")
        return None

# === Ambil semua postingan dari WordPress Self-Hosted REST API (SUMBER) ===
def fetch_raw_posts():
    """
    Mengambil semua postingan yang diterbitkan dari WordPress sumber menggunakan REST API.
    """
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
    """
    Menyisipkan tag <details> setelah sejumlah paragraf tertentu.
    Ini berfungsi sebagai pengganti fungsionalitas 'read more' dengan link eksternal.
    """
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
    print(f"🎯 Akan memposting ke WordPress TARGET via XML-RPC: {WP_TARGET_API_URL} dengan Blog ID: {WP_BLOG_ID}.")
    print("🤖 Fitur Pengeditan Judul dan Konten (300 kata pertama) oleh Gemini AI DIAKTIFKAN.")
    print("📝 Tag [more] akan disisipkan untuk pemotongan di homepage.")
    print("📝 Tag <details> akan disisipkan di dalam artikel untuk link 'Lanjut BAB 2'.")
    print("🖼️ Mencoba menambahkan gambar acak di awal konten.")

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

        # Ambil tanggal dari post_to_publish_data dan format ke YYYY/MM/DD
        post_date_str = post_to_publish_data['date']
        post_datetime_obj = datetime.datetime.fromisoformat(post_date_str.replace('Z', '+00:00'))
        date_path = post_datetime_obj.strftime('%Y/%m/%d')
        print(f"🗓️ Tanggal untuk URL artikel: {date_path}")

        print(f"🌟 Memproses dan menerbitkan artikel berikutnya: '{original_title}' (ID: {original_id}) dari SUMBER")

        title_after_replacements = replace_custom_words(original_title)
        
        content_no_anchors = remove_anchor_tags(original_content)
        cleaned_formatted_content_before_gemini = strip_html_and_divs(content_no_anchors)
        content_after_replacements = replace_custom_words(cleaned_formatted_content_before_gemini)

        # Panggil Gemini AI untuk mengedit judul
        final_edited_title = edit_title_with_gemini(
            title_after_replacements
        )

        # Panggil Gemini AI untuk mengedit 300 kata pertama konten dan menyisipkan [more]
        final_processed_content_text = edit_first_300_words_with_gemini(
            original_id,
            final_edited_title,
            content_after_replacements
        )
        
        # PREDIKSI URL ARTIKEL YANG AKAN TERBIT
        post_slug = slugify(final_edited_title)
        
        # Base URL untuk WordPress.com Anda
        base_target_url_for_permalink = "https://ekstracrot.wordpress.com"

        # Gabungkan base URL, tanggal, dan slug
        predicted_article_url = f"{base_target_url_for_permalink}/{post_datetime_obj.strftime('%Y')}/{post_datetime_obj.strftime('%m')}/{post_slug}/"
        print(f"🔗 Memprediksi URL artikel target: {predicted_article_url}")

        # === Sisipkan tag <details> setelah konten diedit (ini untuk di dalam artikel penuh) ===
        content_with_details_tag = insert_details_tag(
            final_processed_content_text,
            paragraph_limit=10,
            article_url=predicted_article_url,
            article_title=final_edited_title
        )
        
        # Konversi ke HTML untuk pengiriman ke WordPress
        # XML-RPC biasanya menerima HTML, dan '\n\n' akan diinterpretasikan sebagai paragraf baru.
        final_post_content_html = content_with_details_tag.replace('\n\n', '<p></p>')

        published_result = publish_post_to_wordpress(
            WP_TARGET_API_URL,
            WP_BLOG_ID, # Mengirimkan Blog ID ke fungsi publish_post_to_wordpress
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
