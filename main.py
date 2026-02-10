import asyncio
import logging
import json
import time
import random
import sqlite3
import hashlib
import threading
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Pyrogram untuk UserBot (MTProto)
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

# python-telegram-bot untuk Bot Kontrol (Bot API)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters as tg_filters
)

# Flask untuk Web Dashboard
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================ KONFIGURASI ============================

class Config:
    SECRET_KEY = secrets.token_hex(32)
    DATABASE_PATH = "userbot.db"
    FLASK_HOST = "0.0.0.0"
    FLASK_PORT = 5000
    FLASK_DEBUG = True
    BOT_TOKEN = "5593144463:AAFsIwRgGoGXEBQC-kZibnMoMV5BkRwjqIA"  # Token bot Anda
    ADMIN_IDS = [5166575484]  # ID admin
    MAX_MESSAGES_PER_DAY = 1000  # Batas tinggi karena gratis
    DEFAULT_DELAY = 30

# ============================ DATABASE ============================

class Database:
    def __init__(self, db_path: str = Config.DATABASE_PATH):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database tables (versi gratis tanpa payment)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_active INTEGER DEFAULT 1,
                    is_admin INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User sessions (Pyrogram)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    api_id INTEGER,
                    api_hash TEXT,
                    session_string TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_used TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Campaigns table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    name TEXT,
                    message_text TEXT,
                    media_path TEXT,
                    schedule_type TEXT CHECK(schedule_type IN ('interval', 'specific')),
                    interval_minutes INTEGER DEFAULT 60,
                    specific_times TEXT,
                    is_active INTEGER DEFAULT 0,
                    total_sent INTEGER DEFAULT 0,
                    total_failed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Target groups
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS target_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    chat_id INTEGER,
                    chat_title TEXT,
                    thread_id INTEGER DEFAULT 0,
                    delay_seconds INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                )
            ''')
            
            # Message history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    chat_id INTEGER,
                    message_text TEXT,
                    media_path TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT CHECK(status IN ('sent', 'failed', 'pending')),
                    error_message TEXT,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                )
            ''')
            
            # Settings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    user_id INTEGER PRIMARY KEY,
                    max_messages_per_day INTEGER DEFAULT 1000,
                    delay_between_messages INTEGER DEFAULT 30,
                    notification_chat_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            conn.commit()
    
    def create_user(self, telegram_id: int, username: str, first_name: str, last_name: str = ""):
        """Create new user (GRATIS - langsung aktif)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_name, is_active)
                VALUES (?, ?, ?, ?, 1)
            ''', (telegram_id, username, first_name, last_name))
            
            user_id = cursor.lastrowid
            
            # Jika user sudah ada, get ID-nya
            if user_id is None:
                cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
                user = cursor.fetchone()
                user_id = user['id'] if user else None
            
            # Create default settings
            if user_id:
                cursor.execute('''
                    INSERT OR IGNORE INTO settings (user_id, max_messages_per_day, delay_between_messages)
                    VALUES (?, 1000, 30)
                ''', (user_id,))
            
            conn.commit()
            return user_id
    
    def get_user(self, **kwargs):
        """Get user by any field"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if 'id' in kwargs:
                cursor.execute('SELECT * FROM users WHERE id = ?', (kwargs['id'],))
            elif 'telegram_id' in kwargs:
                cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (kwargs['telegram_id'],))
            elif 'username' in kwargs:
                cursor.execute('SELECT * FROM users WHERE username = ?', (kwargs['username'],))
            else:
                return None
            
            return cursor.fetchone()
    
    def save_user_session(self, user_id: int, api_id: int, api_hash: str, session_string: str = ""):
        """Save user session data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_sessions (user_id, api_id, api_hash, session_string, is_active)
                VALUES (?, ?, ?, ?, 1)
            ''', (user_id, api_id, api_hash, session_string))
            conn.commit()
    
    def create_campaign(self, user_id: int, name: str, message_text: str, **kwargs):
        """Create new campaign"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO campaigns 
                (user_id, name, message_text, schedule_type, interval_minutes, is_active)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (
                user_id, name, message_text,
                kwargs.get('schedule_type', 'interval'),
                kwargs.get('interval_minutes', 60),
            ))
            
            campaign_id = cursor.lastrowid
            conn.commit()
            return campaign_id
    
    def add_target_group(self, campaign_id: int, chat_id: int, chat_title: str = "", 
                        thread_id: int = 0, delay: int = 0):
        """Add target group to campaign"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO target_groups (campaign_id, chat_id, chat_title, thread_id, delay_seconds)
                VALUES (?, ?, ?, ?, ?)
            ''', (campaign_id, chat_id, chat_title, thread_id, delay))
            conn.commit()
    
    def get_user_campaigns(self, user_id: int):
        """Get all campaigns for user"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT c.*, 
                       (SELECT COUNT(*) FROM target_groups 
                        WHERE campaign_id = c.id AND is_active = 1) as group_count
                FROM campaigns c
                WHERE c.user_id = ?
                ORDER BY c.created_at DESC
            ''', (user_id,))
            return cursor.fetchall()

# ============================ USERBOT MANAGER ============================

class UserBotManager:
    def __init__(self, db: Database):
        self.db = db
        self.userbots: Dict[int, Client] = {}
        self.active_campaigns: Dict[int, asyncio.Task] = {}
        self.is_running = True
    
    async def create_userbot(self, user_id: int, api_id: int, api_hash: str, telegram_id: int):
        """Create and start a userbot session"""
        try:
            app = Client(
                name=f"userbot_{user_id}",
                api_id=api_id,
                api_hash=api_hash,
                in_memory=True,
                workdir="sessions"
            )
            
            @app.on_message(filters.command("start", prefixes="/") & filters.private)
            async def start_command(client, message: Message):
                await message.reply("🤖 UserBot aktif dan siap untuk promosi otomatis!")
            
            # Start the userbot
            await app.start()
            me = await app.get_me()
            
            # Save session string for future use
            session_string = await app.export_session_string()
            self.db.save_user_session(user_id, api_id, api_hash, session_string)
            
            self.userbots[user_id] = app
            logger.info(f"UserBot started for user {user_id} (Telegram ID: {me.id})")
            return app
            
        except Exception as e:
            logger.error(f"Failed to start UserBot: {e}")
            return None
    
    async def send_promotion_message(self, user_id: int, chat_id: int, 
                                   message_text: str, media_path: str = None,
                                   thread_id: int = 0, delay: int = 0):
        """Send promotion message"""
        if user_id not in self.userbots:
            return False, "UserBot tidak aktif"
        
        if delay > 0:
            await asyncio.sleep(delay)
        
        try:
            app = self.userbots[user_id]
            
            # Check if user is in chat
            try:
                await app.get_chat(chat_id)
            except:
                return False, "Bot tidak ada dalam grup ini"
            
            # Send message
            if media_path and Path(media_path).exists():
                ext = Path(media_path).suffix.lower()
                
                if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    await app.send_photo(
                        chat_id=chat_id,
                        photo=media_path,
                        caption=message_text,
                        message_thread_id=thread_id or None
                    )
                elif ext in ['.mp4', '.mov', '.avi', '.mkv']:
                    await app.send_video(
                        chat_id=chat_id,
                        video=media_path,
                        caption=message_text,
                        message_thread_id=thread_id or None
                    )
                elif ext == '.gif':
                    await app.send_animation(
                        chat_id=chat_id,
                        animation=media_path,
                        caption=message_text,
                        message_thread_id=thread_id or None
                    )
                else:
                    await app.send_document(
                        chat_id=chat_id,
                        document=media_path,
                        caption=message_text,
                        message_thread_id=thread_id or None
                    )
            else:
                await app.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    message_thread_id=thread_id or None
                )
            
            return True, "Pesan berhasil dikirim"
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await self.send_promotion_message(user_id, chat_id, message_text, media_path, thread_id, 0)
        except Exception as e:
            logger.error(f"Send message error: {e}")
            return False, str(e)
    
    async def run_campaign(self, campaign_id: int):
        """Run campaign continuously"""
        while self.is_running:
            try:
                # Get campaign details
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT c.*, u.telegram_id as user_telegram_id
                        FROM campaigns c
                        JOIN users u ON c.user_id = u.id
                        WHERE c.id = ? AND c.is_active = 1
                    ''', (campaign_id,))
                    campaign = cursor.fetchone()
                
                if not campaign:
                    await asyncio.sleep(60)
                    continue
                
                # Get target groups
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT * FROM target_groups 
                        WHERE campaign_id = ? AND is_active = 1
                    ''', (campaign_id,))
                    groups = cursor.fetchall()
                
                if not groups:
                    await asyncio.sleep(60)
                    continue
                
                # Send to each group
                for group in groups:
                    success, message = await self.send_promotion_message(
                        campaign['user_id'],
                        group['chat_id'],
                        campaign['message_text'],
                        campaign['media_path'],
                        group['thread_id'],
                        group['delay_seconds']
                    )
                    
                    # Log in database
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        
                        # Update campaign stats
                        if success:
                            cursor.execute('''
                                UPDATE campaigns 
                                SET total_sent = total_sent + 1 
                                WHERE id = ?
                            ''', (campaign_id,))
                        else:
                            cursor.execute('''
                                UPDATE campaigns 
                                SET total_failed = total_failed + 1 
                                WHERE id = ?
                            ''', (campaign_id,))
                        
                        # Add to message history
                        cursor.execute('''
                            INSERT INTO message_history 
                            (campaign_id, chat_id, message_text, media_path, status, error_message)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (
                            campaign_id,
                            group['chat_id'],
                            campaign['message_text'],
                            campaign['media_path'],
                            'sent' if success else 'failed',
                            None if success else message
                        ))
                        
                        conn.commit()
                    
                    # Delay between groups
                    await asyncio.sleep(random.randint(5, 15))
                
                # Wait based on interval
                await asyncio.sleep(campaign['interval_minutes'] * 60)
                
            except Exception as e:
                logger.error(f"Campaign {campaign_id} error: {e}")
                await asyncio.sleep(60)
    
    async def start_campaign(self, campaign_id: int):
        """Start campaign"""
        if campaign_id in self.active_campaigns:
            return False, "Kampanye sudah berjalan"
        
        task = asyncio.create_task(self.run_campaign(campaign_id))
        self.active_campaigns[campaign_id] = task
        
        # Update database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE campaigns SET is_active = 1 WHERE id = ?', (campaign_id,))
            conn.commit()
        
        return True, "Kampanye dimulai"
    
    async def stop_campaign(self, campaign_id: int):
        """Stop campaign"""
        if campaign_id in self.active_campaigns:
            self.active_campaigns[campaign_id].cancel()
            del self.active_campaigns[campaign_id]
            
            # Update database
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE campaigns SET is_active = 0 WHERE id = ?', (campaign_id,))
                conn.commit()
            
            return True, "Kampanye dihentikan"
        
        return False, "Kampanye tidak ditemukan"

# ============================ CONTROL BOT ============================

class ControlBot:
    def __init__(self, token: str, userbot_manager: UserBotManager, db: Database):
        self.token = token
        self.manager = userbot_manager
        self.db = db
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup bot handlers"""
        # Start command
        self.application.add_handler(CommandHandler("start", self.start_command))
        
        # Setup commands
        self.application.add_handler(CommandHandler("setup", self.setup_command))
        self.application.add_handler(CommandHandler("addcampaign", self.add_campaign_command))
        self.application.add_handler(CommandHandler("addgroup", self.add_group_command))
        self.application.add_handler(CommandHandler("startcampaign", self.start_campaign_command))
        self.application.add_handler(CommandHandler("stopcampaign", self.stop_campaign_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Callback queries
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        
        # Message handlers
        self.application.add_handler(MessageHandler(
            tg_filters.TEXT & ~tg_filters.COMMAND, 
            self.message_handler
        ))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Create user in database
        self.db.create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name or ""
        )
        
        welcome_text = f"""
🤖 **Halo {user.first_name}!**

🎯 **Telegram UserBot Promosi Otomatis - 100% GRATIS**

✨ **Fitur Lengkap GRATIS:**
✅ Promosi otomatis ke grup/chat
✅ Text berbeda untuk grup berbeda
✅ Privasi 100% (data Anda aman)
✅ Support media & hyperlink
✅ Unlimited tanpa batasan
✅ Support grup dengan topik
✅ Kontrol penuh dari bot ini

📋 **Perintah yang tersedia:**
/setup - Setup UserBot Anda dengan API
/addcampaign - Buat kampanye promosi baru
/addgroup - Tambah grup target
/startcampaign - Mulai kampanye
/stopcampaign - Hentikan kampanye
/stats - Lihat statistik pengiriman
/help - Bantuan dan panduan

⚠️ **Gunakan dengan bijak dan patuhi aturan Telegram!**
        """
        
        keyboard = [
            [InlineKeyboardButton("📚 Panduan Lengkap", callback_data="guide")],
            [InlineKeyboardButton("🎬 Video Tutorial", url="https://youtube.com")],
            [InlineKeyboardButton("👨‍💻 Bantuan Admin", url="https://t.me/YourSupport")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def setup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Setup UserBot"""
        user = update.effective_user
        
        setup_text = """
⚙️ **Setup UserBot Anda - GRATIS**

Langkah 1: Dapatkan API ID & Hash
1. Buka https://my.telegram.org
2. Login dengan akun Telegram Anda
3. Klik "API Development Tools"
4. Buat aplikasi baru
5. Copy **API ID** dan **API Hash**

Langkah 2: Kirim dalam format:
`api_id api_hash`

Contoh: `1234567 a1b2c3d4e5f67890abcdef`

⚠️ **Penting:** 
- Jangan bagikan API Hash ke siapapun!
- Pastikan Anda login dengan akun yang ingin digunakan
- Bot ini 100% GRATIS, tidak ada pembayaran
        """
        
        await update.message.reply_text(setup_text, parse_mode='Markdown')
        context.user_data['awaiting_api'] = True
    
    async def add_campaign_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addcampaign command"""
        user = update.effective_user
        
        campaign_text = """
📢 **Buat Kampanye Promosi Baru - GRATIS**

Kirim dalam format:
`nama_kampanye|pesan_promosi|interval_menit`

📝 **Contoh:**
`Promo Toko Online|Halo! Belanja di toko kami www.toko.com...|60`

📊 **Penjelasan:**
- nama_kampanye: Nama untuk identifikasi
- pesan_promosi: Teks yang akan dikirim
- interval_menit: Jarak pengiriman (minimal 30 menit)

💡 **Tips:**
- Gunakan interval minimal 30 menit
- Tambahkan media dengan mengirim file/gambar setelah membuat kampanye
- Test dulu ke 1-2 grup sebelum skala besar
        """
        
        await update.message.reply_text(campaign_text, parse_mode='Markdown')
        context.user_data['awaiting_campaign'] = True
    
    async def add_group_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addgroup command"""
        user = update.effective_user
        
        group_text = """
👥 **Tambahkan Grup Target - GRATIS**

**Cara 1:** Forward pesan dari grup
1. Tambahkan UserBot ke grup Anda
2. Forward pesan apa saja dari grup ke bot ini
3. Sistem otomatis mendeteksi grup

**Cara 2:** Manual dengan ID
Kirim dalam format:
`campaign_id|chat_id|thread_id|delay_detik`

**Penjelasan:**
- campaign_id: ID kampanye (dapat dari /stats)
- chat_id: ID grup/channel
- thread_id: 0 untuk tanpa topik, atau ID topik tertentu
- delay_detik: Jeda sebelum kirim (0 untuk langsung)

📌 **Cara dapatkan chat_id:**
1. Tambahkan @RawDataBot ke grup
2. Lihat ID di pesan yang dikirim
        """
        
        await update.message.reply_text(group_text, parse_mode='Markdown')
        context.user_data['awaiting_group'] = True
    
    async def start_campaign_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /startcampaign command"""
        if context.args:
            try:
                campaign_id = int(context.args[0])
                success, message = await self.manager.start_campaign(campaign_id)
                await update.message.reply_text(f"📤 {message}")
            except ValueError:
                await update.message.reply_text("❌ Format salah. Gunakan: /startcampaign campaign_id")
        else:
            await update.message.reply_text("ℹ️ Gunakan: /startcampaign campaign_id")
    
    async def stop_campaign_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stopcampaign command"""
        if context.args:
            try:
                campaign_id = int(context.args[0])
                success, message = await self.manager.stop_campaign(campaign_id)
                await update.message.reply_text(f"🛑 {message}")
            except ValueError:
                await update.message.reply_text("❌ Format salah. Gunakan: /stopcampaign campaign_id")
        else:
            await update.message.reply_text("ℹ️ Gunakan: /stopcampaign campaign_id")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user = update.effective_user
        
        # Get user from database
        user_data = self.db.get_user(telegram_id=user.id)
        if not user_data:
            await update.message.reply_text("❌ Anda belum terdaftar. Gunakan /start dulu")
            return
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get campaign stats
            cursor.execute('''
                SELECT c.id, c.name, c.is_active, c.total_sent, c.total_failed,
                       (SELECT COUNT(*) FROM target_groups 
                        WHERE campaign_id = c.id AND is_active = 1) as group_count
                FROM campaigns c
                WHERE c.user_id = ?
                ORDER BY c.created_at DESC
            ''', (user_data['id'],))
            
            campaigns = cursor.fetchall()
            
            # Get total stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_campaigns,
                    SUM(total_sent) as total_sent,
                    SUM(total_failed) as total_failed,
                    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_campaigns
                FROM campaigns
                WHERE user_id = ?
            ''', (user_data['id'],))
            
            totals = cursor.fetchone()
        
        if not campaigns:
            stats_text = "📊 **Statistik Anda**\n\n"
            stats_text += "Belum ada kampanye yang dibuat.\n"
            stats_text += "Gunakan /addcampaign untuk membuat kampanye pertama!"
        else:
            stats_text = f"📊 **Statistik Anda**\n\n"
            stats_text += f"📈 **Total:**\n"
            stats_text += f"• Kampanye: {totals['total_campaigns']}\n"
            stats_text += f"• Aktif: {totals['active_campaigns']}\n"
            stats_text += f"• Pesan terkirim: {totals['total_sent'] or 0}\n"
            stats_text += f"• Gagal: {totals['total_failed'] or 0}\n\n"
            
            stats_text += f"📋 **Daftar Kampanye:**\n"
            for campaign in campaigns:
                status = "🟢 Aktif" if campaign['is_active'] else "🔴 Nonaktif"
                stats_text += f"\n**{campaign['name']}** (ID: {campaign['id']})\n"
                stats_text += f"{status} | Grup: {campaign['group_count']}\n"
                stats_text += f"✅ {campaign['total_sent']} | ❌ {campaign['total_failed']}\n"
                stats_text += f"Kontrol: /startcampaign {campaign['id']} | /stopcampaign {campaign['id']}"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help"""
        help_text = """
📚 **Panduan Penggunaan - GRATIS**

🎯 **Langkah-langkah:**
1. **/start** - Mulai bot dan daftar
2. **/setup** - Setup API dari my.telegram.org
3. **/addcampaign** - Buat kampanye promosi
4. **/addgroup** - Tambah grup target
5. **/startcampaign** - Mulai promosi
6. **/stats** - Lihat statistik

⚙️ **Perintah Lengkap:**
/setup - Setup API ID & Hash
/addcampaign - Buat kampanye baru
/addgroup - Tambah grup target
/startcampaign ID - Mulai kampanye
/stopcampaign ID - Hentikan kampanye
/stats - Lihat statistik
/help - Bantuan ini

💡 **Tips Penting:**
• Gunakan interval minimal 30 menit
• Test dulu di 1-2 grup kecil
• Jangan spam! Patuhi aturan grup
• Backup API Anda dengan aman
• Gunakan media untuk hasil lebih baik

❓ **Pertanyaan?**
Hubungi admin: @YourSupport
        """
        
        keyboard = [
            [InlineKeyboardButton("🆘 Bantuan Cepat", url="https://t.me/YourSupport")],
            [InlineKeyboardButton("🎬 Video Tutorial", url="https://youtube.com")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "guide":
            await self.help_command(update, context)
    
    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages"""
        user = update.effective_user
        text = update.message.text
        
        # Get user from database
        user_data = self.db.get_user(telegram_id=user.id)
        if not user_data:
            self.db.create_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name or ""
            )
            user_data = self.db.get_user(telegram_id=user.id)
        
        if context.user_data.get('awaiting_api'):
            try:
                parts = text.split()
                if len(parts) == 2:
                    api_id = int(parts[0])
                    api_hash = parts[1]
                    
                    # Save session data
                    self.db.save_user_session(user_data['id'], api_id, api_hash)
                    
                    # Try to create userbot
                    success = await self.manager.create_userbot(
                        user_data['id'],
                        api_id,
                        api_hash,
                        user.id
                    )
                    
                    if success:
                        await update.message.reply_text(
                            "✅ **Setup berhasil!**\n\n"
                            "UserBot Anda sekarang aktif dan siap digunakan.\n\n"
                            "📌 **Langkah selanjutnya:**\n"
                            "1. /addcampaign - Buat kampanye pertama\n"
                            "2. /addgroup - Tambah grup target\n"
                            "3. /startcampaign - Mulai promosi\n\n"
                            "💡 Bot ini 100% GRATIS!",
                            parse_mode='Markdown'
                        )
                    else:
                        await update.message.reply_text(
                            "⚠️ **API berhasil disimpan, tapi ada masalah saat start UserBot.**\n\n"
                            "Pastikan:\n"
                            "1. API ID & Hash benar\n"
                            "2. Anda sudah login di my.telegram.org\n"
                            "3. Coba ulangi /setup\n\n"
                            "Jika masih error, hubungi admin.",
                            parse_mode='Markdown'
                        )
                else:
                    await update.message.reply_text("❌ Format salah. Gunakan: api_id api_hash")
                
                context.user_data['awaiting_api'] = False
                
            except ValueError:
                await update.message.reply_text("❌ API ID harus berupa angka")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        
        elif context.user_data.get('awaiting_campaign'):
            try:
                parts = text.split('|')
                if len(parts) >= 3:
                    campaign_name = parts[0].strip()
                    message_text = parts[1].strip()
                    interval = int(parts[2].strip())
                    
                    # Minimal interval 30 menit
                    if interval < 30:
                        await update.message.reply_text("⚠️ Interval minimal 30 menit. Diubah ke 30 menit.")
                        interval = 30
                    
                    # Create campaign
                    campaign_id = self.db.create_campaign(
                        user_id=user_data['id'],
                        name=campaign_name,
                        message_text=message_text,
                        interval_minutes=interval
                    )
                    
                    await update.message.reply_text(
                        f"✅ **Kampanye berhasil dibuat!**\n\n"
                        f"**Nama:** {campaign_name}\n"
                        f"**ID Kampanye:** {campaign_id}\n"
                        f"**Interval:** {interval} menit\n\n"
                        f"📌 **Langkah selanjutnya:**\n"
                        f"1. Tambahkan UserBot ke grup target\n"
                        f"2. /addgroup - Tambah grup ke kampanye ini\n"
                        f"3. /startcampaign {campaign_id} - Mulai promosi\n\n"
                        f"💡 Kirim gambar/file untuk menambahkan media ke kampanye ini.",
                        parse_mode='Markdown'
                    )
                    
                    # Store campaign ID for potential media attachment
                    context.user_data['last_campaign_id'] = campaign_id
                    
                else:
                    await update.message.reply_text("❌ Format salah. Gunakan: nama|pesan|interval")
                
                context.user_data['awaiting_campaign'] = False
                
            except ValueError:
                await update.message.reply_text("❌ Interval harus berupa angka (menit)")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        
        elif context.user_data.get('awaiting_group'):
            if update.message.forward_from_chat:
                # Group from forwarded message
                chat = update.message.forward_from_chat
                chat_id = chat.id
                chat_title = chat.title or f"Chat {chat_id}"
                
                await update.message.reply_text(
                    f"✅ **Grup terdeteksi!**\n\n"
                    f"**Nama:** {chat_title}\n"
                    f"**ID:** {chat_id}\n\n"
                    f"📌 **Tambahkan ke kampanye dengan format:**\n"
                    f"`campaign_id|{chat_id}|thread_id|delay`\n\n"
                    f"**Contoh:** `1|{chat_id}|0|30`\n"
                    f"(thread_id: 0, delay: 30 detik)",
                    parse_mode='Markdown'
                )
            else:
                try:
                    parts = text.split('|')
                    if len(parts) == 4:
                        campaign_id = int(parts[0].strip())
                        chat_id = int(parts[1].strip())
                        thread_id = int(parts[2].strip())
                        delay = int(parts[3].strip())
                        
                        # Verify campaign belongs to user
                        with self.db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                SELECT id FROM campaigns 
                                WHERE id = ? AND user_id = ?
                            ''', (campaign_id, user_data['id']))
                            campaign = cursor.fetchone()
                        
                        if not campaign:
                            await update.message.reply_text("❌ Kampanye tidak ditemukan atau bukan milik Anda")
                            return
                        
                        # Add group to campaign
                        self.db.add_target_group(campaign_id, chat_id, "", thread_id, delay)
                        
                        await update.message.reply_text(
                            f"✅ **Grup berhasil ditambahkan!**\n\n"
                            f"**ID Kampanye:** {campaign_id}\n"
                            f"**Chat ID:** {chat_id}\n"
                            f"**Thread ID:** {thread_id}\n"
                            f"**Delay:** {delay} detik\n\n"
                            f"🚀 **Mulai kampanye dengan:**\n"
                            f"/startcampaign {campaign_id}",
                            parse_mode='Markdown'
                        )
                        
                    else:
                        await update.message.reply_text("❌ Format salah. Gunakan: campaign_id|chat_id|thread_id|delay")
                    
                    context.user_data['awaiting_group'] = False
                    
                except ValueError:
                    await update.message.reply_text("❌ Semua nilai harus berupa angka")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def run(self):
        """Start control bot"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("🤖 Control Bot started!")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            await self.application.stop()

# ============================ WEB DASHBOARD SEDERHANA ============================

class WebDashboard:
    def __init__(self, db: Database):
        self.db = db
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = Config.SECRET_KEY
        self.setup_routes()
    
    def setup_routes(self):
        """Setup Flask routes sederhana"""
        
        @self.app.route('/')
        def index():
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Telegram UserBot - GRATIS</title>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        max-width: 800px;
                        margin: 0 auto;
                        padding: 20px;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                    }
                    .container {
                        background: rgba(255, 255, 255, 0.1);
                        padding: 30px;
                        border-radius: 10px;
                        backdrop-filter: blur(10px);
                    }
                    h1 {
                        text-align: center;
                        margin-bottom: 30px;
                    }
                    .feature {
                        background: rgba(255, 255, 255, 0.2);
                        padding: 15px;
                        margin: 10px 0;
                        border-radius: 5px;
                    }
                    .button {
                        display: block;
                        width: 200px;
                        margin: 20px auto;
                        padding: 15px;
                        background: #4CAF50;
                        color: white;
                        text-align: center;
                        text-decoration: none;
                        border-radius: 5px;
                        font-weight: bold;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🤖 Telegram UserBot Promosi Otomatis</h1>
                    <h2>🎯 100% GRATIS - Tanpa Batasan</h2>
                    
                    <div class="feature">✅ Promosi otomatis ke grup/chat</div>
                    <div class="feature">✅ Text berbeda untuk grup berbeda</div>
                    <div class="feature">✅ Privasi 100% (data Anda aman)</div>
                    <div class="feature">✅ Support media & hyperlink</div>
                    <div class="feature">✅ Unlimited tanpa batasan</div>
                    <div class="feature">✅ Support grup dengan topik</div>
                    <div class="feature">✅ Kontrol penuh dari Telegram Bot</div>
                    
                    <h3>🚀 Cara Mulai:</h3>
                    <ol>
                        <li>Buka Telegram dan cari bot @YourBotUsername</li>
                        <li>Klik /start untuk mulai</li>
                        <li>Ikuti panduan di bot</li>
                        <li>Setup API dari my.telegram.org</li>
                        <li>Buat kampanye pertama Anda!</li>
                    </ol>
                    
                    <a href="https://t.me/YourBotUsername" class="button">🚀 Mulai Sekarang</a>
                    
                    <p style="text-align: center; margin-top: 30px;">
                        ❓ Butuh bantuan? Hubungi @YourSupport
                    </p>
                </div>
            </body>
            </html>
            """
        
        @self.app.route('/stats')
        def stats_api():
            """Simple stats API"""
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) as users FROM users')
                users = cursor.fetchone()['users']
                
                cursor.execute('SELECT COUNT(*) as campaigns FROM campaigns')
                campaigns = cursor.fetchone()['campaigns']
                
                cursor.execute('SELECT SUM(total_sent) as sent FROM campaigns')
                sent = cursor.fetchone()['sent'] or 0
                
            return jsonify({
                'status': 'online',
                'users': users,
                'campaigns': campaigns,
                'messages_sent': sent,
                'version': '1.0',
                'free': True
            })
        
        @self.app.route('/health')
        def health():
            return jsonify({'status': 'healthy', 'free': True})
    
    def run(self):
        """Run Flask app"""
        self.app.run(
            host=Config.FLASK_HOST,
            port=Config.FLASK_PORT,
            debug=Config.FLASK_DEBUG,
            threaded=True
        )

# ============================ MAIN APPLICATION ============================

async def main():
    """Main function"""
    logger.info("🚀 Starting Telegram UserBot - VERSI GRATIS")
    
    # Initialize database
    db = Database()
    
    # Initialize userbot manager
    manager = UserBotManager(db)
    
    # Start web dashboard in separate thread
    web_dashboard = WebDashboard(db)
    web_thread = threading.Thread(
        target=web_dashboard.run,
        daemon=True
    )
    web_thread.start()
    logger.info(f"🌐 Web dashboard started on http://{Config.FLASK_HOST}:{Config.FLASK_PORT}")
    
    # Start control bot
    control_bot = ControlBot(Config.BOT_TOKEN, manager, db)
    
    try:
        await control_bot.run()
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Error: {e}")

if __name__ == "__main__":
    # Install packages jika belum
    import subprocess
    import sys
    
    required_packages = [
        'pyrogram',
        'python-telegram-bot',
        'flask',
        'werkzeug',
        'flask-login'
    ]
    
    print("🔧 Checking dependencies...")
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            print(f"📦 Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    
    print("✅ All dependencies installed!")
    
    # Jalankan aplikasi
    asyncio.run(main())
