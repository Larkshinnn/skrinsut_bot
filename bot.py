"""Discord DM bot: kirim gambar/video -> otomatis tersimpan di Google Drive (kualitas asli)."""

import asyncio
import hashlib
import logging
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ss_saver")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
ROOT_FOLDER_ID = os.environ["DRIVE_ROOT_FOLDER_ID"]
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Jakarta"))
# Kanal server tempat bot boleh bekerja (pisahkan dengan koma). Kosong = semua kanal. DM selalu boleh.
ALLOWED_CHANNEL_IDS = {int(x) for x in os.getenv("ALLOWED_CHANNEL_IDS", "").replace(" ", "").split(",") if x}

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_LABEL = "(Folder utama)"
MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tiff",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".3gp",
}


# --------------------------------------------------------------------------- Google Drive

CREDS = Credentials(
    None,
    refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    token_uri="https://oauth2.googleapis.com/token",
    scopes=SCOPES,
)


def _drive():
    # Satu service per panggilan: httplib2 tidak thread-safe, dan kita pakai asyncio.to_thread.
    return build("drive", "v3", credentials=CREDS, cache_discovery=False)


def _list_folders() -> list[tuple[str, str]]:
    """Daftar (nama, id) subfolder langsung di dalam folder utama."""
    folders, token = [], None
    query = f"'{ROOT_FOLDER_ID}' in parents and mimeType='{FOLDER_MIME}' and trashed=false"
    while True:
        res = _drive().files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            orderBy="name",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        folders += [(f["name"], f["id"]) for f in res.get("files", [])]
        token = res.get("nextPageToken")
        if not token:
            return folders


def _create_folder(name: str) -> str:
    body = {"name": name, "mimeType": FOLDER_MIME, "parents": [ROOT_FOLDER_ID]}
    return _drive().files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"]


def _upload(path: Path, name: str, mime: str, parent_id: str) -> dict:
    media = MediaFileUpload(str(path), mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
    return _drive().files().create(
        body={"name": name, "parents": [parent_id]},
        media_body=media,
        fields="id, name, webViewLink, md5Checksum, size",
        supportsAllDrives=True,
    ).execute()


_folder_cache: tuple[float, list[tuple[str, str]]] = (0.0, [])


async def list_folders(max_age: float = 30.0) -> list[tuple[str, str]]:
    global _folder_cache
    if time.monotonic() - _folder_cache[0] > max_age:
        _folder_cache = (time.monotonic(), await asyncio.to_thread(_list_folders))
    return _folder_cache[1]


async def resolve_folder(text: str) -> tuple[str, str] | None:
    """Cari folder dari teks user: nama persis (case-insensitive), lalu awalan unik.
    Awali dengan '+' untuk membuat folder baru, mis. '+Kuliah'."""
    text = text.strip()
    if text.startswith("+") and text[1:].strip():
        name = text[1:].strip()
        folder_id = await asyncio.to_thread(_create_folder, name)
        await list_folders(max_age=0)  # refresh cache
        return name, folder_id

    folders = await list_folders(max_age=0)
    key = text.lower()
    exact = [f for f in folders if f[0].lower() == key]
    if exact:
        return exact[0]
    prefix = [f for f in folders if f[0].lower().startswith(key)]
    return prefix[0] if len(prefix) == 1 else None


# --------------------------------------------------------------------------- Simpan file

def is_media(att: discord.Attachment) -> bool:
    ctype = (att.content_type or "").lower()
    return ctype.startswith(("image/", "video/")) or Path(att.filename).suffix.lower() in MEDIA_EXTS


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_name(text: str) -> str | None:
    """Rapikan nama file dari user; None kalau kosong."""
    text = text.strip().replace("/", "-").replace("\\", "-")
    return text or None


def file_name(att: discord.Attachment, stamp: str, i: int, total: int, new_name: str | None) -> str:
    suffix = f"_{i}" if total > 1 else ""
    if not new_name:
        return f"{stamp}{suffix}_{att.filename}"
    ext = Path(att.filename).suffix
    if ext and new_name.lower().endswith(ext.lower()):  # user sudah menulis ekstensinya
        new_name = new_name[: -len(ext)]
    return f"{new_name}{suffix}{ext}"


async def save_attachments(message: discord.Message, attachments: list[discord.Attachment],
                           folder_name: str, folder_id: str, new_name: str | None = None) -> str:
    stamp = message.created_at.astimezone(TZ).strftime("%Y-%m-%d_%H-%M-%S")
    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, att in enumerate(attachments, 1):
            name = file_name(att, stamp, i, len(attachments), new_name)
            path = Path(tmp) / f"{i}{Path(att.filename).suffix}"
            mime = (att.content_type or "").split(";")[0] or mimetypes.guess_type(att.filename)[0] \
                or "application/octet-stream"
            try:
                # att.save() mengunduh file ORIGINAL dari CDN Discord (bukan preview yang di-resize).
                await att.save(path, use_cached=False)
                local_md5 = md5_of(path)
                res = await asyncio.to_thread(_upload, path, name, mime, folder_id)
                ok = res.get("md5Checksum") == local_md5
                mark = "✅" if ok else "⚠️ (checksum beda!)"
                lines.append(f"{mark} [{res['name']}](<{res['webViewLink']}>) — {int(res['size']) / 1e6:.2f} MB")
            except Exception as e:  # noqa: BLE001 - laporkan per file, lanjut ke file berikutnya
                log.exception("Gagal upload %s", att.filename)
                lines.append(f"❌ `{att.filename}`: {e}")
    return f"📁 **{folder_name}**\n" + "\n".join(lines)


# --------------------------------------------------------------------------- Discord UI

class SaveView(discord.ui.View):
    """Dropdown folder (dari Drive) + tombol Simpan (nama asli) / Rename."""

    def __init__(self, message: discord.Message, attachments: list[discord.Attachment],
                 folders: list[tuple[str, str]], folder: tuple[str, str] | None = None):
        super().__init__(timeout=600)
        self.message, self.attachments = message, attachments
        self.folder = folder or (ROOT_LABEL, ROOT_FOLDER_ID)
        # Folder utama + folder terpilih selalu ada di daftar (batas Discord: 25 opsi).
        choices = [(ROOT_LABEL, ROOT_FOLDER_ID)]
        if self.folder[1] != ROOT_FOLDER_ID:
            choices.append(self.folder)
        choices += [f for f in folders if f[1] != self.folder[1]]
        choices = choices[:25]
        self.names = {fid: name for name, fid in choices}
        self.select = discord.ui.Select(
            placeholder="Pilih folder tujuan...",
            options=[discord.SelectOption(label=name[:100], value=fid, default=fid == self.folder[1])
                     for name, fid in choices],
            row=0,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == OWNER_ID

    async def on_select(self, interaction: discord.Interaction):
        fid = self.select.values[0]
        self.folder = (self.names[fid], fid)
        for opt in self.select.options:
            opt.default = opt.value == fid
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Simpan", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def save_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.upload(interaction, None)

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def rename_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(RenameModal(self))

    async def upload(self, interaction: discord.Interaction, new_name: str | None):
        self.stop()
        name, fid = self.folder
        await interaction.response.edit_message(content=f"⏳ Mengupload ke **{name}**...", view=None)
        result = await save_attachments(self.message, self.attachments, name, fid, new_name)
        await interaction.edit_original_response(content=result)


class RenameModal(discord.ui.Modal, title="Rename file"):
    def __init__(self, save_view: SaveView):
        super().__init__()
        self.save_view = save_view
        atts = save_view.attachments
        self.new_name = discord.ui.TextInput(
            label="Nama file baru (ekstensi otomatis)",
            default=Path(atts[0].filename).stem[:200] if len(atts) == 1 else None,
            placeholder=f"{len(atts)} file → nama_1, nama_2, ..." if len(atts) > 1 else None,
            max_length=200,
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        await self.save_view.upload(interaction, clean_name(self.new_name.value))


# Message Content Intent wajib supaya isi & lampiran pesan di channel server terbaca
# (aktifkan juga di Developer Portal > Bot > Privileged Gateway Intents).
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def setup_hook():
    await tree.sync()


@client.event
async def on_ready():
    log.info("Login sebagai %s", client.user)


HELP = (
    "Kirim gambar/video ke sini, bisa sekalian tulis nama folder di caption.\n"
    "• Caption `game` → folder **game** terpilih (boleh huruf awal saja, mis. `ga`)\n"
    "• Caption `+Kuliah` → buat folder baru **Kuliah**\n"
    "• Lalu klik **Simpan** (nama asli) atau **Rename** (ketik nama baru)\n"
    "• Caption `game | liburan bali` → langsung simpan ke **game** dengan nama `liburan bali`\n"
    "• Tanpa caption → pilih folder dari dropdown\n"
    "• Ketik `folders` → lihat daftar folder\n"
    "• Atau pakai slash command `/save`"
)


def channel_allowed(channel) -> bool:
    """DM selalu boleh; di server hanya kanal di ALLOWED_CHANNEL_IDS (thread ikut kanal induknya)."""
    if isinstance(channel, discord.DMChannel) or not ALLOWED_CHANNEL_IDS:
        return True
    channel_id = channel.parent_id if isinstance(channel, discord.Thread) else channel.id
    return channel_id in ALLOWED_CHANNEL_IDS


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not channel_allowed(message.channel):
        return
    is_dm = isinstance(message.channel, discord.DMChannel)
    if message.author.id != OWNER_ID:
        if is_dm:
            await message.channel.send("Bot ini privat 🙏")
        return  # di server: abaikan orang lain tanpa spam

    media = [a for a in message.attachments if is_media(a)]
    caption = message.content.strip()

    if not media:
        if caption.lower() in {"folders", "folder", "list", "ls"}:
            folders = await list_folders(max_age=0)
            body = "\n".join(f"• {name}" for name, _ in folders) or "_(belum ada subfolder)_"
            await message.channel.send(f"📂 Folder yang tersedia:\n{body}")
        elif is_dm:  # di server jangan balas setiap chat biasa
            await message.channel.send(HELP)
        return

    # Caption: "folder" atau "folder | nama baru" (folder kosong = folder utama).
    folder_text, _, name_text = caption.partition("|")
    folder_text, new_name = folder_text.strip(), clean_name(name_text)
    folder, note = None, ""
    if folder_text:
        folder = await resolve_folder(folder_text)
        if not folder:
            note = f"Folder `{folder_text}` tidak ditemukan. "
    elif new_name:
        folder = (ROOT_LABEL, ROOT_FOLDER_ID)

    if folder and new_name:  # folder & nama sudah lengkap → langsung upload
        status = await message.channel.send(f"⏳ Mengupload {len(media)} file ke **{folder[0]}**...")
        await status.edit(content=await save_attachments(message, media, *folder, new_name))
        return

    folders = await list_folders(max_age=0)
    await message.channel.send(
        f"{note}{len(media)} file — pilih folder, lalu **Simpan** (nama asli) atau **Rename**.",
        view=SaveView(message, media, folders, folder),
    )


@tree.command(name="save", description="Simpan gambar/video ke Google Drive")
@app_commands.describe(file="Gambar atau video", folder="Folder tujuan (kosongkan = folder utama)",
                       nama="Nama file baru tanpa ekstensi (kosongkan = nama asli)")
async def save_cmd(interaction: discord.Interaction, file: discord.Attachment, folder: str | None = None,
                   nama: str | None = None):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Bot ini privat 🙏", ephemeral=True)
        return
    if not channel_allowed(interaction.channel):
        allowed = " ".join(f"<#{cid}>" for cid in ALLOWED_CHANNEL_IDS)
        await interaction.response.send_message(f"Pakai di {allowed} 🙏", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    if folder:
        target = await resolve_folder(folder)
        if not target:
            await interaction.followup.send(f"Folder `{folder}` tidak ditemukan.")
            return
    else:
        target = (ROOT_LABEL, ROOT_FOLDER_ID)
    msg = await interaction.original_response()
    await interaction.followup.send(await save_attachments(msg, [file], *target, clean_name(nama or "")))


@save_cmd.autocomplete("folder")
async def folder_autocomplete(interaction: discord.Interaction, current: str):
    folders = await list_folders()
    cur = current.lower()
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n, _ in folders if cur in n.lower()][:25]


if __name__ == "__main__":
    client.run(DISCORD_TOKEN, log_handler=None)
