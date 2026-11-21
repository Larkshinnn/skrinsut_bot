# ss_saver

Bot Discord (lewat DM) yang menyimpan gambar & video ke Google Drive dengan kualitas asli.
Setiap upload dicek MD5-nya: ✅ berarti file di Drive identik byte-per-byte dengan yang dikirim lewat Discord.

## Cara pakai (di DM bot)

| Kirim | Hasil |
|---|---|
| gambar/video + caption `game` | folder `game` sudah terpilih (boleh huruf awal saja, mis. `ga`) → klik **Simpan** atau **Rename** |
| gambar/video + caption `+Kuliah` | buat subfolder baru `Kuliah` → klik **Simpan** atau **Rename** |
| gambar/video tanpa caption | pilih folder dari dropdown → klik **Simpan** atau **Rename** |
| gambar/video + caption `game \| liburan bali` | langsung disimpan ke `game` sebagai `liburan bali.jpg` |
| `folders` | daftar subfolder |
| `/save file:<file> folder:<autocomplete> nama:<opsional>` | slash command, nama folder di-autocomplete dari Drive |

Di server, isi `ALLOWED_CHANNEL_IDS` (pisahkan koma) supaya bot hanya bekerja di kanal tertentu. DM selalu boleh. Agar bot juga tidak bisa *membaca* kanal lain, atur izin role bot di Discord (lihat README Ronova bagian "Batasi bot ke kanal tertentu").

Nama file:
- **Simpan** → `2026-11-13_14-05-22_namaasli.png` (waktu pesan dikirim).
- **Rename** → nama yang kamu ketik, ekstensi ditambahkan otomatis. Kalau kirim beberapa file sekaligus: `nama_1.png`, `nama_2.mp4`, ...

## Setup

### 1. Discord bot
1. https://discord.com/developers/applications → **New Application** → tab **Bot** → **Reset Token** → simpan sebagai `DISCORD_TOKEN`.
   Di tab yang sama, aktifkan **Message Content Intent** (wajib agar bot bisa membaca gambar di channel server).
2. Tab **Installation** → centang **Guild Install**, scope `bot` + `applications.commands` → buka link install, masukkan ke server mana saja milikmu (perlu satu server bersama agar bisa DM bot). Setelah itu buka profil bot → **Message**.
3. Discord → Settings → Advanced → **Developer Mode** ON → klik kanan profilmu → **Copy User ID** → `OWNER_ID`.

### 2. Google Drive (OAuth)
> Service account tidak bisa upload ke Drive pribadi (tidak punya kuota), jadi dipakai OAuth akun Google kamu sendiri.

1. https://console.cloud.google.com → buat project → **APIs & Services → Library** → enable **Google Drive API**.
2. **OAuth consent screen** → External → isi seperlunya → tambahkan email kamu sebagai test user.
   Lalu klik **Publish app** (status *In production*). **Penting:** kalau tetap *Testing*, refresh token kedaluwarsa tiap 7 hari.
3. **Credentials → Create credentials → OAuth client ID → Desktop app** → download JSON, simpan sebagai `client_secret.json` di folder ini.
4. Jalankan:
   ```
   pip install google-auth-oauthlib
   python get_token.py
   ```
   Login di browser (abaikan peringatan "Google hasn't verified this app" → Advanced → Go to ...). Salin 3 nilai yang dicetak.
5. Buka folder utama di Drive, ambil ID dari URL `https://drive.google.com/drive/folders/<ID>` → `DRIVE_ROOT_FOLDER_ID`.

### 3. Jalankan lokal (opsional)
```
cp .env.example .env   # isi semua nilai
pip install -r requirements.txt
python bot.py
```

### 4. Deploy ke Railway
1. Push folder ini ke GitHub (`.env` & `client_secret.json` sudah di-ignore).
2. Railway → **New Project → Deploy from GitHub repo**.
3. Tab **Variables** → isi semua variabel dari `.env.example`.
4. Selesai. Start command sudah diatur di `railway.json` (`python bot.py`). Tidak perlu domain/port karena bot ini worker.

## Catatan kualitas
- Bot mengunduh file **original** dari CDN Discord (bukan preview yang di-resize) dan meng-upload tanpa konversi apa pun.
- Batas ukuran file mengikuti Discord: 10 MB (akun biasa), lebih besar kalau Nitro.
- Discord sendiri menghapus sebagian metadata EXIF (mis. lokasi) saat upload. Pikselnya tetap sama, tapi metadata itu memang sudah hilang sebelum sampai ke bot.
