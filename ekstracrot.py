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
from wordpress_xmlrpc.methods.media import UploadFile

# --- Konfigurasi ---
API_SOURCE_URL = "https://kisah69.blog/wp-json/wp/v2/posts"
WP_TARGET_API_URL = "https://ekstracrot.wordpress.com/xmlrpc.php"
WP_BLOG_ID = "137050535" 

STATE_FILE = 'artikel_terbit.json'
RANDOM_IMAGES_FILE = 'random_images.json'

# --- DEFAULT TAGS ---
DEFAULT_TAGS = ["Cerita Dewasa", "Cerita Seks", "Cerita Sex", "Cerita Ngentot"]

# --- Konfigurasi Gemini API ---
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

# Utilitas dan Fungsi Pembantu
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
    Ini adalah versi yang MENGHAPUS SEMUA TAG HTML, termasuk komentar.
    """
    if html is None:
        html = ""

    processed_text = re.sub(r'</p>', r'\n\n', html, flags=re.IGNORECASE)
    processed_text = re.sub(r'<img[^>]*>', '', processed_text)
    processed_text = re.sub(r'</?div[^>]*>', '', processed_text, flags=re.IGNORECASE)
    
    processed_text = re.sub('<[^<]+?>', '', processed_text) 
    
    processed_text = re.sub(r'\n{3,}', r'\n\n', processed_text).strip()
    return processed_text

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

# Fungsi Utama Pengolahan Konten (Gemini Diaktifkan Kembali)
def edit_first_300_words_with_gemini(post_id, post_title, full_text_content):
    """
    Mengedit 300 kata pertama dari konten artikel menggunakan Gemini AI.
    Fungsi ini akan mengembalikan seluruh konten yang sudah diedit, dan juga 300 kata pertama yang sudah diedit.
    """
    words = full_text_content.split()
    
    # Jika artikel terlalu pendek, lewati pengeditan AI tapi tetap bersihkan
    if len(words) < 50:
        print(f"[{post_id}] Artikel terlalu pendek (<50 kata) untuk diedit oleh Gemini AI. Melewati pengeditan.")
        cleaned_content = strip_html_and_divs(replace_custom_words(full_text_content))
        # Mengembalikan seluruh konten yang dibersihkan, dan 300 kata pertama (sebenarnya kurang dari 300)
        return cleaned_content, cleaned_content 

    char_count_for_300_words = 0
    word_count = 0
    # Hitung jumlah karakter untuk 300 kata
    for i, word in enumerate(words):
        if word_count < 300:
            char_count_for_300_words += len(word)
            if i < len(words) - 1: # Tambahkan spasi antar kata
                char_count_for_300_words += 1
            word_count += 1
        else:
            break
            
    # Pastikan tidak melebihi panjang teks asli
    char_count_for_300_words = min(char_count_for_300_words, len(full_text_content))
    first_300_words_original_string = full_text_content[:char_count_for_300_words].strip()
    rest_of_article_text = full_text_content[char_count_for_300_words:].strip()

    print(f"🤖 Memulai pengeditan Gemini AI (Model Konten) untuk artikel ID: {post_id} - '{post_title}' ({len(first_300_words_original_string.split())} kata pertama)...")
    try:
        processed_first_300_words = replace_custom_words(first_300_words_original_string)

        prompt = (
            f"Saya ingin Anda menulis ulang paragraf pembuka dari sebuah cerita. "
            f"Tujuannya adalah untuk membuat narasi yang mengalir, menarik perhatian pembaca, dan mempertahankan inti cerita asli, "
            f"tetapi dengan gaya bahasa yang lebih halus dan sopan, menghindari bahasa yang eksplisit atau vulgar. "
            f"Paragraf harus tetap panjangnya sekitar 300 kata dari teks asli, tetapi dengan kosakata dan struktur kalimat yang diubah secara signifikan. "
            f"Gunakan gaya informal dan lugas. Pastikan tidak ada konten yang melanggar pedoman keamanan.\n\n"
            f"Berikut adalah paragraf aslinya:\n\n"
            f"{processed_first_300_words}"
            f"\n\nParagraf yang ditulis ulang:"
        )
        response = gemini_model_content.generate_content(prompt)
        edited_text_from_gemini = response.text
        print(f"✅ Gemini AI (Model Konten) selesai mengedit bagian pertama artikel ID: {post_id}.")
        
        cleaned_edited_text_from_gemini = strip_html_and_divs(edited_text_from_gemini)
        
        # Gabungkan hasil edit Gemini dengan sisa artikel asli yang sudah diganti kata-katanya
        final_combined_text = cleaned_edited_text_from_gemini.strip() + "\n\n" + replace_custom_words(rest_of_article_text).strip()
        
        fully_cleaned_content = strip_html_and_divs(final_combined_text)
        
        # Mengembalikan seluruh konten yang sudah bersih DAN 300 kata pertama yang sudah diedit
        return fully_cleaned_content, cleaned_edited_text_from_gemini 

    except Exception as e:
        print(f"❌ Error saat mengedit dengan Gemini AI (Model Konten) untuk artikel ID: {post_id} - {e}. Menggunakan teks asli untuk bagian ini.")
        content_after_replacements = replace_custom_words(full_text_content)
        cleaned_content = strip_html_and_divs(content_after_replacements)
        # Jika ada error, tetap kembalikan konten asli dan 300 kata pertama (yang tidak diedit oleh Gemini)
        return cleaned_content, content_after_replacements.split()[:300] # Mengembalikan 300 kata pertama dari yang sudah diganti kata

def edit_title_with_gemini(original_title, edited_first_300_words_context):
    """
    Mengedit judul menggunakan Gemini AI agar lebih menarik, tidak vulgar, dan
    menggunakan peran/pekerjaan tokoh wanita yang ditemukan di 300 kata pertama.
    """
    print(f"🤖 Memulai pengeditan judul dengan Gemini AI (Model Judul): '{original_title}' berdasarkan 300 kata pertama yang diedit...")
    try:
        prompt = (
            f"Saya membutuhkan SATU judul baru yang sangat menarik (clickbait) dan tidak vulgar, tetap relevan, serta mengandung kata 'Cerita Dewasa'. "
            f"Paling penting, cari dan gunakan peran atau pekerjaan tokoh wanita yang mungkin disebutkan di awal cerita sebagai bagian dari judul untuk membuatnya lebih spesifik dan memancing rasa penasaran (misalnya: 'istri pejabat', 'guru', 'mahasiswi', 'dokter'). "
            f"Jika tidak ada peran atau pekerjaan yang jelas, sebutkan bagian tubuh peran wanita saja"
            f"Judul harus singkat dan padat.\n\n"
            f"Berikut adalah 300 kata pertama dari artikel yang sudah diedit:\n\n"
            f"```\n{edited_first_300_words_context}\n```\n\n" # Konteks dari 300 kata yang sudah diedit
            f"**HANYA BERIKAN SATU JUDUL BARU, TANPA PENJELASAN ATAU TEKS TAMBAHAN APAPUN.**\n\n"
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

# Fungsi Manajemen State dan Gambar (Tidak Berubah)
def load_published_posts_state():
    # ... (Kode ini tidak berubah) ...
    pass

def save_published_posts_state(published_ids):
    # ... (Kode ini tidak berubah) ...
    pass

def load_image_urls(file_path):
    # ... (Kode ini tidak berubah) ...
    pass

def get_random_image_url(image_urls):
    # ... (Kode ini tidak berubah) ...
    pass

# Fungsi Sisipan Tag Khusus (<details>) (Tidak Berubah)
def insert_details_tag(content_text, article_url=None, article_title=None):
    # ... (Kode ini tidak berubah) ...
    pass

# Fungsi BARU: Sisipkan <!--more--> Tepat Sebelum Pengiriman (Tidak Berubah)
def add_more_tag_before_send(content_text):
    # ... (Kode ini tidak berubah) ...
    pass

# Fungsi Publikasi ke WordPress (Tidak Berubah)
def publish_post_to_wordpress(wp_xmlrpc_url, blog_id, title, content_html, username, app_password, random_image_url=None, post_status='publish', tags=None):
    # ... (Kode ini tidak berubah) ...
    pass

# Fungsi Ambil Post dari Sumber (Tidak Berubah)
def fetch_raw_posts():
    # ... (Kode ini tidak berubah) ...
    pass

# Eksekusi Utama
if __name__ == '__main__':
    print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting WordPress to WordPress publishing process...")
    print(f"🚀 Mengambil artikel dari WordPress SUMBER: {API_SOURCE_URL}.")
    print(f"🎯 Akan memposting ke WordPress TARGET via XML-RPC: {WP_TARGET_API_URL} dengan Blog ID: {WP_BLOG_ID}.")
    print("🤖 Fitur Pengeditan Judul dan Konten (300 kata pertama) oleh Gemini AI DIAKTIFKAN.")
    print("📝 Tag <details> akan disisipkan di dalam artikel di pertengahan total paragraf.")
    print("📝 Tag <!--more--> akan disisipkan setelah paragraf pertama TEPAT SEBELUM pengiriman ke WordPress.")
    print("🖼️ Mencoba menambahkan gambar acak di awal konten.")
    print(f"🏷️ Tag default yang akan ditambahkan: {', '.join(DEFAULT_TAGS)}")

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

        # Penggantian kata khusus dan pembersihan HTML untuk konten asli (sebelum diproses Gemini)
        content_no_anchors = remove_anchor_tags(original_content)
        cleaned_content_before_gemini = strip_html_and_divs(content_no_anchors)
        content_after_replacements_all = replace_custom_words(cleaned_content_before_gemini)

        # 1. Panggil fungsi edit konten terlebih dahulu untuk mendapatkan 300 kata pertama yang sudah diedit
        # 'edited_first_300_words_content' akan berisi 300 kata pertama yang sudah bersih dan diedit oleh Gemini
        final_processed_content_text, edited_first_300_words_content = edit_first_300_words_with_gemini(
            original_id,
            original_title, # Gunakan original_title di sini untuk logging
            content_after_replacements_all # Masukkan konten yang sudah bersih dan diganti kata ke Gemini
        )
        
        # 2. Kemudian, gunakan 300 kata pertama yang sudah diedit tersebut sebagai konteks untuk mengedit judul
        final_edited_title = edit_title_with_gemini(
            replace_custom_words(original_title), # Judul asli juga perlu penggantian kata sebelum ke Gemini
            edited_first_300_words_content # TERUSKAN SELURUH 300 KATA PERTAMA YANG SUDAH DIEDIT DI SINI
        )
        
        post_slug = slugify(final_edited_title)
        base_target_url_for_permalink = "https://ekstracrot.wordpress.com"
        predicted_article_url = f"{base_target_url_for_permalink}/{post_datetime_obj.strftime('%Y')}/{post_datetime_obj.strftime('%m')}/{post_slug}"
        print(f"🔗 Memprediksi URL artikel target: {predicted_article_url}")

        content_with_details_tag = insert_details_tag(
            final_processed_content_text,
            article_url=predicted_article_url,
            article_title=final_edited_title
        )
        
        # LANGKAH KRUSIAL: Sisipkan <!--more--> Paling Akhir
        final_content_before_html_conversion = add_more_tag_before_send(content_with_details_tag)

        # Konversi ke HTML untuk pengiriman ke WordPress
        # Pastikan format <!--more--> diubah menjadi untuk WordPress
        final_post_content_html = final_content_before_html_conversion.replace('\n\n', '</p><p>').replace('<!--more-->', '')
        if not final_post_content_html.startswith('<p>'):
            final_post_content_html = '<p>' + final_post_content_html
        if not final_post_content_html.endswith('</p>'):
            final_post_content_html = final_post_content_html + '</p>'


        published_result = publish_post_to_wordpress(
            WP_TARGET_API_URL,
            WP_BLOG_ID,
            final_edited_title,
            final_post_content_html,
            WP_USERNAME,
            WP_APP_PASSWORD,
            random_image_url=selected_random_image,
            tags=DEFAULT_TAGS 
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
